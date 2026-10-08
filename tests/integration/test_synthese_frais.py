"""
Synthese des notes de frais validees transmise a la comptabilite (CDC fonctionnel 3) : e-mail a la
validation finale, ecran de synthese et export CSV.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.demande import Demande
from app.models.enums import RoleEtape, RoleUtilisateur, StatutDemande, StatutEtape, TypeProcessus
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.taux_change import TauxChange
from app.models.user import Utilisateur
from app.services import decision_tokens, synthese_frais
from app.services.rappels import settings as _  # noqa: F401 (charge les reglages)

COMPTA = "compta@organisation.tld"


async def _u(db, role, service="Ventes", nom=None, manager_id=None):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h", nom_complet=nom or f"Test {role.value}",
                    service=service, role=role, manager_id=manager_id)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.fixture
def emails(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.services.email_service.envoyer_email", mock)
    return mock


@pytest.fixture(autouse=True)
def compta_configuree(monkeypatch):
    from app.routers import decisions

    monkeypatch.setattr(decisions.settings, "comptabilite_email", COMPTA)


async def _note_validee(db, employe, approbateur, *, montant=100.0, devise="EUR", taux=1.0, ref=None, categorie="Repas",
                        description="x", quand=None, statut=StatutDemande.TERMINEE, derogation=False, date_depense="2026-03-01"):
    d = Demande(processus=TypeProcessus.NOTES_FRAIS, demandeur_id=employe.id, initiee_par_id=employe.id, statut_global=statut,
                donnees={"montant": montant, "devise": devise, "taux_applique": taux, "montant_reference": ref if ref is not None else montant,
                         "categorie": categorie, "date_depense": date_depense, "description": description})
    db.add(d)
    await db.flush()
    db.add(EtapeWorkflow(demande_id=d.id, niveau=1, role=RoleEtape.APPROBATEUR, approbateur_attendu_id=approbateur.id,
                         statut=StatutEtape.APPROUVE if statut == StatutDemande.TERMINEE else StatutEtape.REFUSE,
                         date_reponse=quand or datetime.now(UTC), est_derogation=derogation))
    await db.commit()
    return d


@pytest.fixture
async def acteurs(db_session):
    manager = await _u(db_session, RoleUtilisateur.MANAGER, nom="Marie Manager")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Eric Employe", manager_id=manager.id)
    return manager, employe


# --- e-mail a la validation finale -------------------------------------------------------------

async def _soumettre_et_approuver(client, db_session, employe, manager, montant=120):
    app.dependency_overrides[get_current_user] = lambda: employe
    r = await client.post("/api/v1/notes-frais/", json={"montant": montant, "categorie": "Transport", "date_depense": "2026-03-01", "description": "Train"})
    app.dependency_overrides.pop(get_current_user, None)
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(r.json()["premiere_etape_id"]), "approuver", manager.id)
    await db_session.commit()
    return r, await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=_h(manager))


def _mails_compta(mock):
    return [a.kwargs for a in mock.call_args_list if a.kwargs.get("destinataire") == COMPTA]


async def test_la_comptabilite_recoit_la_synthese_a_la_validation_finale_et_la_transmission_est_tracee(client, db_session, acteurs, emails):
    manager, employe = acteurs
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=5000))
    await db_session.commit()

    _, decision = await _soumettre_et_approuver(client, db_session, employe, manager)

    assert decision.json()["statut_global"] == "terminee"
    mails = _mails_compta(emails)
    assert len(mails) == 1
    assert "💶 Note de frais validée à rembourser — Eric Employe" == mails[0]["sujet"]
    corps = mails[0]["corps_html"]
    for attendu in ("Eric Employe (Ventes)", "Transport", "01/03/2026", "Train", "120.0 €", "Marie Manager"):
        assert attendu in corps
    trace = (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "synthese_comptabilite_envoyee"))).scalar_one()
    assert trace.details == {"destinataire": COMPTA} and trace.acteur_id is None


async def test_aucun_email_comptabilite_pour_un_refus(client, db_session, acteurs, emails):
    manager, employe = acteurs
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=5000))
    await db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: employe
    r = await client.post("/api/v1/notes-frais/", json={"montant": 50, "categorie": "Repas", "date_depense": "2026-03-01", "description": "x"})
    app.dependency_overrides.pop(get_current_user, None)
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(r.json()["premiere_etape_id"]), "refuser", manager.id)
    await db_session.commit()

    await client.post(f"/api/v1/decisions/{jeton}", json={"commentaire": "Non"}, headers=_h(manager))

    assert _mails_compta(emails) == []


async def test_un_seul_email_meme_avec_escalade_et_seulement_a_la_validation_finale(client, db_session, acteurs, emails):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance", nom="Diane DF")
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=5000))
    await db_session.commit()

    _, niveau1 = await _soumettre_et_approuver(client, db_session, employe, manager, montant=800)  # > 500 : escalade
    assert niveau1.json()["statut_global"] == "en_cours"
    assert _mails_compta(emails) == []  # rien apres le premier niveau

    etape2 = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.niveau == 2))).scalar_one()
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "approuver", df.id)
    await db_session.commit()
    await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=_h(df))

    mails = _mails_compta(emails)
    assert len(mails) == 1 and "Marie Manager, Diane DF" in mails[0]["corps_html"]  # chaine de validation dans l'ordre


async def test_sans_adresse_configuree_aucun_email_et_la_decision_passe(client, db_session, acteurs, emails, monkeypatch):
    from app.routers import decisions

    monkeypatch.setattr(decisions.settings, "comptabilite_email", "")
    manager, employe = acteurs
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=5000))
    await db_session.commit()

    _, decision = await _soumettre_et_approuver(client, db_session, employe, manager)

    assert decision.json()["statut_global"] == "terminee" and _mails_compta(emails) == []


async def test_un_echec_d_envoi_ne_bloque_pas_la_decision_et_n_est_pas_trace_comme_transmis(client, db_session, acteurs, emails):
    manager, employe = acteurs
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=5000))
    await db_session.commit()

    async def echoue_pour_la_compta(**kw):
        if kw.get("destinataire") == COMPTA:
            raise RuntimeError("Resend indisponible")

    emails.side_effect = echoue_pour_la_compta
    _, decision = await _soumettre_et_approuver(client, db_session, employe, manager)

    assert decision.status_code == 200 and decision.json()["statut_global"] == "terminee"  # la decision n'est pas remise en cause
    assert (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "synthese_comptabilite_envoyee"))).first() is None


async def test_l_email_montre_le_montant_d_origine_le_taux_fige_et_echappe_les_champs_saisis(db_session, acteurs):
    manager, employe = acteurs
    d = await _note_validee(db_session, employe, manager, montant=800.0, devise="USD", taux=0.92, ref=736.0,
                            categorie="<b>Hack</b>", description="<script>x</script>", derogation=True)

    ligne = await synthese_frais.ligne_de(db_session, d)
    corps = synthese_frais.corps_email_html(ligne)

    assert "800.0 USD" in corps and "736.0 €" in corps and "1 USD = 0.92 €" in corps
    assert "Oui (dérogation)" in corps
    assert "<script>" not in corps and "<b>Hack</b>" not in corps and "&lt;script&gt;" in corps


# --- ecran de synthese ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [RoleUtilisateur.DRH, RoleUtilisateur.DIRECTION_FINANCIERE, RoleUtilisateur.CONTROLEUR_DE_GESTION])
async def test_les_roles_financiers_consultent_la_synthese(client, db_session, role):
    u = await _u(db_session, role)
    for chemin in ("/api/v1/notes-frais/synthese", "/api/v1/notes-frais/synthese.csv"):
        assert (await client.get(chemin, headers=_h(u))).status_code == 200


@pytest.mark.parametrize("role", [RoleUtilisateur.EMPLOYE, RoleUtilisateur.MANAGER, RoleUtilisateur.DIRECTION_GENERALE, RoleUtilisateur.SERVICE_JURIDIQUE])
async def test_les_autres_roles_n_y_ont_pas_acces(client, db_session, role):
    u = await _u(db_session, role)
    for chemin in ("/api/v1/notes-frais/synthese", "/api/v1/notes-frais/synthese.csv"):
        assert (await client.get(chemin, headers=_h(u))).status_code == 403


async def test_seules_les_notes_validees_apparaissent(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    await _note_validee(db_session, employe, manager, description="validee")
    await _note_validee(db_session, employe, manager, description="refusee", statut=StatutDemande.REFUSEE)
    d = Demande(processus=TypeProcessus.NOTES_FRAIS, demandeur_id=employe.id, initiee_par_id=employe.id, statut_global=StatutDemande.EN_COURS,
                donnees={"montant": 5, "categorie": "x", "date_depense": "2026-03-01", "description": "en cours"})
    db_session.add(d)
    autre = Demande(processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id, statut_global=StatutDemande.TERMINEE, donnees={})
    db_session.add(autre)
    await db_session.commit()

    r = (await client.get("/api/v1/notes-frais/synthese", headers=_h(df))).json()

    assert [e["description"] for e in r["elements"]] == ["validee"] and r["nombre"] == 1


async def test_totaux_par_devise_et_total_converti(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    await _note_validee(db_session, employe, manager, montant=100.0)
    await _note_validee(db_session, employe, manager, montant=200.0, devise="USD", taux=0.9, ref=180.0)
    await _note_validee(db_session, employe, manager, montant=300.0, devise="USD", taux=0.8, ref=240.0)  # autre taux, fige

    r = (await client.get("/api/v1/notes-frais/synthese", headers=_h(df))).json()

    assert r["devise_reference"] == "EUR" and r["nombre"] == 3 and r["total_reference"] == 520.0
    assert r["par_devise"] == [
        {"devise": "EUR", "nombre": 1, "total": 100.0, "total_reference": 100.0},
        {"devise": "USD", "nombre": 2, "total": 500.0, "total_reference": 420.0},
    ]


async def test_les_totaux_portent_sur_toute_la_selection_pas_sur_la_page(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    for i in range(5):
        await _note_validee(db_session, employe, manager, montant=10.0, quand=datetime.now(UTC) - timedelta(minutes=i))

    page = (await client.get("/api/v1/notes-frais/synthese", params={"limit": 2}, headers=_h(df))).json()

    assert len(page["elements"]) == 2 and page["nombre"] == 5 and page["total_reference"] == 50.0


async def test_filtres_par_periode_de_validation_et_par_service(client, db_session, acteurs):
    manager, employe = acteurs
    finance = await _u(db_session, RoleUtilisateur.EMPLOYE, service="Finance", nom="Fred Finance")
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    await _note_validee(db_session, employe, manager, description="mars", quand=datetime(2026, 3, 15, 12, tzinfo=UTC))
    await _note_validee(db_session, employe, manager, description="fin-mars", quand=datetime(2026, 3, 31, 23, 30, tzinfo=UTC))
    await _note_validee(db_session, finance, manager, description="avril-finance", quand=datetime(2026, 4, 2, 9, tzinfo=UTC))
    get = lambda **p: client.get("/api/v1/notes-frais/synthese", params=p, headers=_h(df))

    assert {e["description"] for e in (await get(depuis="2026-03-01", jusqu_a="2026-03-31")).json()["elements"]} == {"mars", "fin-mars"}  # 31/03 inclus
    assert [e["description"] for e in (await get(depuis="2026-04-01")).json()["elements"]] == ["avril-finance"]
    assert [e["description"] for e in (await get(service="Finance")).json()["elements"]] == ["avril-finance"]
    assert (await get(depuis="2027-01-01")).json()["nombre"] == 0


async def test_chaque_ligne_porte_l_auteur_les_validateurs_et_le_montant_fige(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    await _note_validee(db_session, employe, manager, montant=800.0, devise="USD", taux=0.92, ref=736.0, derogation=True)

    ligne = (await client.get("/api/v1/notes-frais/synthese", headers=_h(df))).json()["elements"][0]

    assert (ligne["demandeur_nom"], ligne["service"], ligne["valide_par"], ligne["derogation"]) == ("Eric Employe", "Ventes", ["Marie Manager"], True)
    assert (ligne["montant"], ligne["devise"], ligne["taux_applique"], ligne["montant_reference"]) == (800.0, "USD", 0.92, 736.0)


# --- export CSV ----------------------------------------------------------------------------------

async def test_le_csv_est_exploitable_sous_excel_francophone(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    await _note_validee(db_session, employe, manager, montant=1234.5, devise="USD", taux=0.92, ref=1135.74, categorie="Hôtel", description='Nuit "spéciale"; à Paris')

    r = await client.get("/api/v1/notes-frais/synthese.csv", headers=_h(df))

    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="synthese-notes-de-frais-')
    assert r.content.startswith("\ufeff".encode("utf-8"))  # BOM : les accents restent corrects
    lignes = r.content.decode("utf-8").lstrip("\ufeff").split("\r\n")
    assert lignes[0].split(";")[0] == "Date de validation" and "Montant en EUR" in lignes[0]
    assert '"Nuit ""spéciale""; à Paris"' in lignes[1]                  # guillemets doubles, separateur protege
    assert "1234,50;USD;0,92;1135,74" in lignes[1]                     # decimales a virgule


async def test_le_csv_neutralise_l_injection_de_formule(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    for i, danger in enumerate(('=HYPERLINK("http://evil","clic")', "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)")):
        await _note_validee(db_session, employe, manager, description=danger, categorie=f"cat{i}")

    corps = (await client.get("/api/v1/notes-frais/synthese.csv", headers=_h(df))).content.decode("utf-8")

    for danger in ("'=HYPERLINK", "'+cmd", "'-2+3", "'@SUM"):
        assert danger in corps
    for cellule in corps.split("\r\n")[1:-1]:
        for champ in cellule.split(";"):
            assert not champ.startswith(("=", "+", "-", "@")) or champ.startswith('"'), champ  # jamais de formule active


def test_neutralisation_unitaire():
    assert synthese_frais.neutraliser("=1+1") == "'=1+1"
    assert synthese_frais.neutraliser("\t=1") == "'\t=1"
    assert synthese_frais.neutraliser("Repas") == "Repas" and synthese_frais.neutraliser("") == ""
    assert synthese_frais.neutraliser("12-03") == "12-03"  # un tiret au milieu n'est pas une formule


async def test_l_export_couvre_toute_la_selection_et_est_trace_au_journal(client, db_session, acteurs):
    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    for _i in range(230):  # plus d'une page de 200
        db_session.add(Demande(processus=TypeProcessus.NOTES_FRAIS, demandeur_id=employe.id, initiee_par_id=employe.id, statut_global=StatutDemande.TERMINEE,
                               donnees={"montant": 1.0, "categorie": "x", "date_depense": "2026-03-01", "description": "lot"}))
    await db_session.flush()
    for d in (await db_session.execute(select(Demande))).scalars():
        db_session.add(EtapeWorkflow(demande_id=d.id, niveau=1, role=RoleEtape.APPROBATEUR, approbateur_attendu_id=manager.id,
                                     statut=StatutEtape.APPROUVE, date_reponse=datetime.now(UTC)))
    await db_session.commit()

    r = await client.get("/api/v1/notes-frais/synthese.csv", params={"service": "Ventes"}, headers=_h(df))

    assert len(r.content.decode("utf-8").strip().split("\r\n")) == 231  # en-tete + 230 lignes
    trace = (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "synthese_frais_exportee"))).scalar_one()
    assert trace.acteur_id == df.id and trace.details["lignes"] == 230 and trace.details["service"] == "Ventes"


async def test_la_consultation_de_l_ecran_n_est_pas_journalisee_seul_l_export_l_est(client, db_session):
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    await client.get("/api/v1/notes-frais/synthese", headers=_h(df))
    assert (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "synthese_frais_exportee"))).first() is None


# --- acces aux recus pour la comptabilite, strictement borne --------------------------------------

async def test_la_comptabilite_lit_les_recus_des_notes_validees_et_rien_d_autre(client, db_session, acteurs):
    from app.models.piece_jointe import PieceJointe
    from app.services import stockage_fichiers

    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    controleur = await _u(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION)
    validee = await _note_validee(db_session, employe, manager)
    en_cours = await _note_validee(db_session, employe, manager, statut=StatutDemande.EN_COURS)
    achat = Demande(processus=TypeProcessus.ACHATS, demandeur_id=employe.id, initiee_par_id=employe.id, statut_global=StatutDemande.TERMINEE, donnees={})
    conge = Demande(processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id, statut_global=StatutDemande.TERMINEE, donnees={})
    db_session.add_all([achat, conge])
    await db_session.flush()
    pieces = {}
    for nom, d in (("validee", validee), ("en_cours", en_cours), ("achat", achat), ("conge", conge)):
        cle = stockage_fichiers.enregistrer_fichier(b"%PDF " + nom.encode(), f"{nom}.pdf")
        p = PieceJointe(demande_id=d.id, nom_original=f"{nom}.pdf", cle_stockage=cle, categorie="recu")
        db_session.add(p)
        pieces[nom] = (d, p)
    await db_session.commit()

    async def peut_lire(qui, nom):
        d, p = pieces[nom]
        return (await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes/{p.id}", headers=_h(qui))).status_code

    for qui in (df, controleur):
        assert await peut_lire(qui, "validee") == 200            # recu d'une note VALIDEE : oui
        assert await peut_lire(qui, "en_cours") == 403           # note pas encore validee : non
        assert await peut_lire(qui, "achat") == 403              # achat : non
        assert await peut_lire(qui, "conge") == 403              # conge : non


async def test_le_nombre_de_pieces_de_la_synthese_compte_les_recus(client, db_session, acteurs):
    from app.models.piece_jointe import PieceJointe

    manager, employe = acteurs
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE)
    d = await _note_validee(db_session, employe, manager)
    db_session.add(PieceJointe(demande_id=d.id, nom_original="r.pdf", cle_stockage="k", categorie="recu"))
    await db_session.commit()

    ligne = (await client.get("/api/v1/notes-frais/synthese", headers=_h(df))).json()["elements"][0]

    assert ligne["nb_pieces"] == 1
