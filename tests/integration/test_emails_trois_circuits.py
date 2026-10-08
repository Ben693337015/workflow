"""
E-mails des trois circuits (conges, notes de frais, achats), de bout en bout.

Les messages sont interceptes tout au bout de la chaine, la ou le service appelle Resend (`resend.Emails.send`) :
c'est le VRAI chemin d'envoi (expediteur, destinataire, sujet, corps). Pour chaque circuit on verifie, a chaque etape :
le bon destinataire, un sujet et un corps complets, les liens de decision - et surtout que **le lien recu par e-mail
fonctionne reellement** (il est extrait du message puis utilise pour decider). Le nom du demandeur contient du HTML
volontairement : il ne doit jamais apparaitre brut dans un corps d'e-mail.
"""
import os
import re
import uuid
from datetime import UTC, datetime

import pytest
import resend
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleUtilisateur
from app.models.etape_workflow import EtapeWorkflow
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur

settings = get_settings()
ANNEE = datetime.now(UTC).year
NOM_PIEGE = "Léa <i>O'Neil</i>"          # HTML + apostrophe : doit etre echappe dans tous les corps
SIGNATURE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


@pytest.fixture
def boite(monkeypatch):
    """Tous les e-mails sortis vers Resend, dans l'ordre."""
    envoyes = []
    monkeypatch.setattr(resend.Emails, "send", lambda payload: envoyes.append(payload))
    yield envoyes
    # Revue visuelle : EMAILS_DUMP=<dossier> ecrit chaque message en .html (ouvrable dans un navigateur).
    dossier = os.environ.get("EMAILS_DUMP")
    if dossier:
        os.makedirs(dossier, exist_ok=True)
        nom = re.sub(r"[^a-z0-9]+", "-", os.environ.get("PYTEST_CURRENT_TEST", "t").split("::")[1].split(" ")[0].lower())
        for i, m in enumerate(envoyes):
            with open(f"{dossier}/{nom}-{i}.html", "w", encoding="utf-8") as f:
                f.write(f"<!-- to: {m['to']} | subject: {m['subject']} -->\n{m['html']}")


async def _u(db, role, nom=None, service="Ventes", manager_id=None):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=nom or f"Test {role.value}", service=service, role=role, manager_id=manager_id)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


async def _budget(db, alloue=100000, service="Ventes"):
    db.add(EnveloppeBudgetaire(service=service, exercice=ANNEE, budget_alloue=alloue))
    await db.commit()


def _destinataires(mail):
    return mail["to"]


def _liens(mail):
    """[(jeton, libelle)] des liens de decision du corps."""
    return re.findall(r"href='[^']*/decisions/([A-Za-z0-9_\-]+)'>([^<]+)</a>", mail["html"])


def _jeton(mail, libelle):
    return next(j for j, l in _liens(mail) if l == libelle)


def _a(boite, email):
    return [m for m in boite if email in m["to"]]


def _verifier_tous(boite):
    """Invariants valables pour CHAQUE e-mail sorti."""
    assert boite, "aucun e-mail envoye"
    for m in boite:
        assert m["from"] == settings.email_from
        assert len(m["to"]) == 1 and "@" in m["to"][0], m
        assert m["subject"].strip() and m["html"].strip()
        assert "None" not in m["html"] and "{" not in m["html"] and "}" not in m["html"], m["html"]
        assert "<i>" not in m["html"], f"HTML du demandeur non echappe dans : {m['subject']}\n{m['html']}"
        for lien in re.findall(r"href='([^']+)'", m["html"]):
            assert lien.startswith(settings.frontend_base_url), lien


async def _decider(client, jeton, user, corps=None):
    return await client.post(f"/api/v1/decisions/{jeton}", json=corps or {}, headers=_h(user))


# ============================================================================ CONGES
async def _conges(client, db, boite):
    manager = await _u(db, RoleUtilisateur.MANAGER)
    drh = await _u(db, RoleUtilisateur.DRH)
    emp = await _u(db, RoleUtilisateur.EMPLOYE, nom=NOM_PIEGE, manager_id=manager.id)
    tc = TypeConge(code=f"cp{uuid.uuid4().hex[:4]}", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db.add(tc)
    await db.flush()
    db.add(SoldeConges(utilisateur_id=emp.id, type_conge_id=tc.id, solde_jours=20, jours_acquis=20, jours_pris=0, exercice=2026))
    await db.commit()
    r = await client.post("/api/v1/conges/", json={"type_conge_id": str(tc.id), "date_debut": "2026-06-01",
                                                   "date_fin": "2026-06-03"}, headers=_h(emp))
    assert r.status_code == 201, r.text
    return emp, manager, drh


async def test_conges_approbation_tous_les_emails(client, db_session, boite):
    emp, manager, drh = await _conges(client, db_session, boite)

    # 1. soumission -> manager, avec liens
    [m1] = boite
    assert _destinataires(m1) == [manager.email] and "congé" in m1["subject"].lower()
    assert {l for _j, l in _liens(m1)} == {"Approuver", "Refuser"}
    # 2. le lien reçu par e-mail fonctionne (session du manager) -> DRH + demandeur
    r = await _decider(client, _jeton(m1, "Approuver"), manager)
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    assert len(boite) == 3
    mail_drh, mail_emp = _a(boite, drh.email)[0], _a(boite, emp.email)[0]
    assert "approuvé" in mail_drh["subject"].lower() and "pour information" in mail_drh["subject"].lower()
    assert "01/06/2026" in mail_drh["html"] and "03/06/2026" in mail_drh["html"] and "3 jour" in mail_drh["html"]
    assert "approuvée" in mail_emp["subject"] and "01/06/2026" in mail_emp["subject"]
    # le jeton est consomme : le meme lien ne decide pas deux fois
    assert (await _decider(client, _jeton(m1, "Approuver"), manager)).status_code in (400, 401, 403, 404, 409, 410)
    _verifier_tous(boite)


async def test_conges_refus_motif_transmis_au_demandeur_et_a_la_drh(client, db_session, boite):
    emp, manager, drh = await _conges(client, db_session, boite)
    r = await _decider(client, _jeton(boite[0], "Refuser"), manager, {"commentaire": "Période de clôture <b>annuelle</b>"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    mail_emp, mail_drh = _a(boite, emp.email)[0], _a(boite, drh.email)[0]
    assert "refusée" in mail_emp["subject"] and "Période de clôture" in mail_emp["html"]
    assert "<b>annuelle</b>" not in mail_emp["html"]                     # motif echappe
    assert "refusé" in mail_drh["subject"].lower()
    _verifier_tous(boite)


# ============================================================================ NOTES DE FRAIS
async def _note(client, emp, montant, extra=None):
    corps = {"montant": montant, "categorie": "Repas", "date_depense": f"{ANNEE}-03-01", "description": "x", **(extra or {})}
    r = await client.post("/api/v1/notes-frais/", json=corps, headers=_h(emp))
    assert r.status_code == 201, r.text
    return r.json()


async def test_note_de_frais_simple_approbation(client, db_session, boite, monkeypatch):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom=NOM_PIEGE, manager_id=manager.id)
    await _budget(db_session)
    monkeypatch.setattr("app.routers.decisions.settings.comptabilite_email", "compta@e.com")

    await _note(client, emp, 120.0)
    [m1] = boite
    assert _destinataires(m1) == [manager.email] and "note de frais" in m1["subject"].lower()
    assert "120" in m1["html"] and "Solde" in m1["html"]                  # montant + solde budgetaire (CDC 4.3)
    r = await _decider(client, _jeton(m1, "Approuver"), manager)
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    # comptabilite (synthese) + demandeur, pas de 2e niveau
    assert len(boite) == 3
    assert "à rembourser" in _a(boite, "compta@e.com")[0]["subject"]
    mail_emp = _a(boite, emp.email)[0]
    assert "approuvée" in mail_emp["subject"] and "120" in mail_emp["subject"]
    _verifier_tous(boite)


async def test_note_de_frais_au_dela_du_seuil_escalade_vers_la_direction_financiere(client, db_session, boite, monkeypatch):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Karim Fofana", manager_id=manager.id)
    await _budget(db_session)
    monkeypatch.setattr("app.routers.decisions.settings.comptabilite_email", "")

    await _note(client, emp, 700.0)
    r = await _decider(client, _jeton(boite[0], "Approuver"), manager)
    assert r.status_code == 200 and r.json()["statut_global"] == "en_cours"
    # la Direction financiere est prevenue, le demandeur PAS encore (decision non finale)
    assert len(boite) == 2 and _destinataires(boite[1]) == [df.email]
    mail_df = boite[1]
    assert "montant élevé" in mail_df["subject"].lower() and "Karim Fofana" in mail_df["html"]   # nom non mis en minuscules
    assert {l for _j, l in _liens(mail_df)} == {"Approuver", "Refuser"}
    # le lien recu par la Direction financiere fonctionne
    r2 = await _decider(client, _jeton(mail_df, "Approuver"), df)
    assert r2.status_code == 200 and r2.json()["statut_global"] == "terminee"
    assert "approuvée" in _a(boite, emp.email)[0]["subject"]
    _verifier_tous(boite)


async def test_note_de_frais_refus_motif_et_derogation_vers_la_direction_financiere(client, db_session, boite):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    ctrl = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom=NOM_PIEGE, manager_id=manager.id)
    # --- refus par le manager
    await _budget(db_session)
    await _note(client, emp, 50.0)
    r = await _decider(client, _jeton(boite[0], "Refuser"), manager, {"commentaire": "Justificatif illisible"})
    assert r.status_code == 200
    mail = _a(boite, emp.email)[0]
    assert "refusée" in mail["subject"] and "Justificatif illisible" in mail["html"]
    boite.clear()
    # --- depassement budgetaire : derogation -> direction financiere (pas le manager)
    await _note(client, emp, 90000.0 * 2, {"derogation_motivee": True, "motif_derogation": "Mission <b>urgente</b>"})
    [m1] = boite
    assert _destinataires(m1) == [ctrl.email] and "dérogation" in m1["subject"].lower()
    assert "Mission" in m1["html"] and "<b>urgente</b>" not in m1["html"]
    r = await _decider(client, _jeton(m1, "Approuver"), ctrl, {"justification_acceptation": "Client strategique"})
    assert r.status_code == 200
    assert "approuvée" in _a(boite, emp.email)[0]["subject"]
    _verifier_tous(boite)


# ============================================================================ ACHATS
async def _achat(client, emp, tiers="Fournisseur <b>X</b>"):
    r = await client.post("/api/v1/achats/", headers=_h(emp),
                          data={"tiers": tiers, "objet": "Licences", "budget_engage": "100"},
                          files={"fichier_contrat": ("c.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


async def test_achat_juridique_puis_signature_de_la_direction_generale(client, db_session, boite):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom=NOM_PIEGE)
    await _budget(db_session)

    await _achat(client, emp)
    [m1] = boite
    assert _destinataires(m1) == [jur.email] and "achat" in m1["subject"].lower()
    assert "<b>X</b>" not in m1["html"] and "Fournisseur" in m1["html"]
    r = await _decider(client, _jeton(m1, "Approuver"), jur)
    assert r.status_code == 200 and r.json()["statut_global"] == "en_cours"
    # la DG est prevenue ; son action est « signer » : le lien doit le dire (et fonctionner)
    assert len(boite) == 2 and _destinataires(boite[1]) == [dg.email]
    mail_dg = boite[1]
    libelles = {l for _j, l in _liens(mail_dg)}
    assert libelles == {"Signer", "Refuser"}, f"libelles du lien de la DG : {libelles}"
    r2 = await _decider(client, _jeton(mail_dg, "Signer"), dg, {"signature_image_base64": SIGNATURE})
    assert r2.status_code == 200 and r2.json()["statut_global"] == "terminee"
    mail_emp = _a(boite, emp.email)[0]
    assert "approuvée" in mail_emp["subject"] and "<b>X</b>" not in mail_emp["html"]
    _verifier_tous(boite)


async def test_achat_refus_du_juridique_notifie_le_demandeur_avec_le_motif(client, db_session, boite):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom=NOM_PIEGE)
    await _budget(db_session)
    await _achat(client, emp)
    r = await _decider(client, _jeton(boite[0], "Refuser"), jur, {"commentaire": "Clause <u>abusive</u>"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    assert len(boite) == 2                                  # pas d'e-mail a la DG : le circuit s'arrete
    mail = _a(boite, emp.email)[0]
    assert "refusée" in mail["subject"] and "Clause" in mail["html"] and "<u>" not in mail["html"]
    _verifier_tous(boite)


# ============================================================================ RELANCE + RESILIENCE
async def test_la_relance_renvoie_un_lien_valide_pour_chaque_circuit(client, db_session, boite):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom=NOM_PIEGE, manager_id=manager.id)
    await _budget(db_session)
    note = await _note(client, emp, 60.0)
    achat = await _achat(client, emp)
    for demande, route, approbateur in ((note, "notes-frais", manager), (achat, "achats", jur)):
        avant = len(boite)
        r = await client.post(f"/api/v1/{route}/{demande['id']}/relancer", headers=_h(emp))
        assert r.status_code == 200 and r.json()["email_envoye"] is True
        mail = boite[avant]
        assert _destinataires(mail) == [approbateur.email] and "Rappel" in mail["subject"]
        assert (await _decider(client, _jeton(mail, "Approuver"), approbateur)).status_code == 200
    _verifier_tous(boite)


async def test_une_panne_de_resend_ne_bloque_aucun_circuit(client, db_session, monkeypatch):
    def _panne(payload):
        raise RuntimeError("Resend indisponible")

    monkeypatch.setattr(resend.Emails, "send", _panne)
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    # congés
    tc = TypeConge(code="cpx", nom="CP", taux_acquisition_jours_mois=2.5)
    db_session.add(tc)
    await db_session.flush()
    db_session.add(SoldeConges(utilisateur_id=emp.id, type_conge_id=tc.id, solde_jours=20, jours_acquis=20, jours_pris=0, exercice=2026))
    await db_session.commit()
    rc = await client.post("/api/v1/conges/", json={"type_conge_id": str(tc.id), "date_debut": "2026-06-01", "date_fin": "2026-06-02"}, headers=_h(emp))
    note = await _note(client, emp, 40.0)
    achat = await _achat(client, emp)
    assert rc.status_code == 201
    # decisions : les jetons sont lus en base (aucun e-mail n'est arrive)
    from app.services import decision_tokens
    for did, approbateur, corps in ((rc.json()["id"], manager, {}), (note["id"], manager, {}), (achat["id"], jur, {})):
        etape = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(did)))).scalars().first()
        j = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", approbateur.id)
        await db_session.commit()
        assert (await _decider(client, j, approbateur, corps)).status_code == 200
