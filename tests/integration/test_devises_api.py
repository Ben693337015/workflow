"""
Plusieurs devises avec conversion (decision du 28/09) : taux de change, conversion a la soumission,
seuil et budget compares au montant CONVERTI, taux FIGE sur la demande.
"""
from tests.signature_factory import SIGNATURE_PNG
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.taux_change import TauxChange
from app.models.user import Utilisateur
from app.services import decision_tokens, devises
from app.services.extensions import suivi_budgetaire

AUJOURDHUI = datetime.now(UTC).date()


async def _u(db, role, service="Ventes", manager_id=None):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h", nom_complet=f"Test {role.value}",
                    service=service, role=role, manager_id=manager_id)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


async def _taux(db, devise, taux, date_effet=date(2026, 1, 1)):
    db.add(TauxChange(devise=devise, taux=taux, date_effet=date_effet))
    await db.commit()


async def _budget(db, alloue, exercice=2026):
    db.add(EnveloppeBudgetaire(service="Ventes", exercice=exercice, budget_alloue=alloue))
    await db.commit()


@pytest.fixture
def emails(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.services.email_service.envoyer_email", mock)
    return mock


async def _note(client, employe, montant, devise=None, date_depense="2026-03-01", **extra):
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        corps = {"montant": montant, "categorie": "Materiel", "date_depense": date_depense, "description": "x", **extra}
        if devise:
            corps["devise"] = devise
        return await client.post("/api/v1/notes-frais/", json=corps)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def equipe(db_session):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    return manager, employe


# --- gestion des taux ------------------------------------------------------------------

@pytest.mark.parametrize("role", [RoleUtilisateur.DRH, RoleUtilisateur.CONTROLEUR_DE_GESTION, RoleUtilisateur.DIRECTION_FINANCIERE])
async def test_les_roles_financiers_definissent_les_taux(client, db_session, role):
    u = await _u(db_session, role)
    r = await client.put("/api/v1/taux-change/", json={"devise": "usd", "taux": 0.92, "date_effet": "2026-01-01"}, headers=_h(u))
    assert r.status_code == 200 and r.json()["devise"] == "USD" and r.json()["taux"] == 0.92


@pytest.mark.parametrize("role", [RoleUtilisateur.EMPLOYE, RoleUtilisateur.MANAGER, RoleUtilisateur.DIRECTION_GENERALE, RoleUtilisateur.SERVICE_JURIDIQUE])
async def test_les_autres_roles_ne_touchent_pas_aux_taux(client, db_session, role):
    u = await _u(db_session, role)
    assert (await client.put("/api/v1/taux-change/", json={"devise": "USD", "taux": 0.9, "date_effet": "2026-01-01"}, headers=_h(u))).status_code == 403
    assert (await client.get("/api/v1/taux-change/", headers=_h(u))).status_code == 403


async def test_un_taux_est_idempotent_et_consigne_avant_apres(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    corps = {"devise": "USD", "date_effet": "2026-01-01"}
    await client.put("/api/v1/taux-change/", json={**corps, "taux": 0.90}, headers=_h(drh))
    await client.put("/api/v1/taux-change/", json={**corps, "taux": 0.95}, headers=_h(drh))

    assert len((await client.get("/api/v1/taux-change/", headers=_h(drh))).json()) == 1  # meme (devise, date) : corrige, pas duplique
    journal = (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "taux_change_defini").order_by(JournalAudit.horodate_le))).scalars().all()
    assert [(j.details["taux_avant"], j.details["taux_apres"]) for j in journal] == [(None, 0.90), (0.90, 0.95)]
    assert all(j.acteur_id == drh.id for j in journal)


@pytest.mark.parametrize("corps", [
    {"devise": "EUR", "taux": 1.0, "date_effet": "2026-01-01"},      # devise de reference
    {"devise": "dollar", "taux": 0.9, "date_effet": "2026-01-01"},   # pas un code ISO
    {"devise": "US", "taux": 0.9, "date_effet": "2026-01-01"},
    {"devise": "USD", "taux": 0, "date_effet": "2026-01-01"},
    {"devise": "USD", "taux": -1, "date_effet": "2026-01-01"},
])
async def test_taux_invalides_refuses(client, db_session, corps):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    assert (await client.put("/api/v1/taux-change/", json=corps, headers=_h(drh))).status_code == 422


async def test_les_devises_utilisables_excluent_un_taux_pas_encore_en_vigueur(client, db_session):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _taux(db_session, "USD", 0.92, date(2026, 1, 1))
    await _taux(db_session, "GBP", 1.15, AUJOURDHUI + timedelta(days=30))  # a venir

    r = (await client.get("/api/v1/devises/", headers=_h(employe))).json()

    assert r["reference"] == "EUR"
    assert [d["code"] for d in r["devises"]] == ["EUR", "USD"]
    assert r["devises"][0] == {"code": "EUR", "taux": 1.0, "date_effet": None}


async def test_conversion_a_la_demande_pour_l_apercu(client, db_session):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _taux(db_session, "USD", 0.90, date(2026, 1, 1))
    await _taux(db_session, "USD", 0.95, date(2026, 6, 1))
    get = lambda **p: client.get("/api/v1/devises/convertir", params=p, headers=_h(employe))

    assert (await get(montant=100, devise="USD", date="2026-03-01")).json()["montant_reference"] == 90.0
    assert (await get(montant=100, devise="USD", date="2026-07-01")).json()["montant_reference"] == 95.0
    inconnue = await get(montant=100, devise="GBP", date="2026-07-01")
    assert inconnue.status_code == 422 and "GBP" in inconnue.json()["detail"]


# --- notes de frais converties -----------------------------------------------------------

async def test_la_conversion_est_figee_sur_la_demande_et_exposee(client, db_session, equipe):
    manager, employe = equipe
    await _taux(db_session, "USD", 0.92)
    await _budget(db_session, 5000)

    r = await _note(client, employe, 800, "usd")

    assert r.status_code == 201
    assert (r.json()["devise"], r.json()["taux_applique"], r.json()["montant_reference"]) == ("USD", 0.92, 736.0)
    liste = (await client.get("/api/v1/notes-frais/", headers=_h(employe))).json()
    d = liste[0]["donnees"]
    assert (d["montant"], d["devise"], d["taux_applique"], d["montant_reference"]) == (800.0, "USD", 0.92, 736.0)


async def test_le_taux_retenu_est_celui_de_la_date_de_la_depense(client, db_session, equipe):
    _, employe = equipe
    await _taux(db_session, "USD", 0.90, date(2026, 1, 1))
    await _taux(db_session, "USD", 0.95, date(2026, 6, 1))
    await _budget(db_session, 5000)

    avant = await _note(client, employe, 100, "USD", date_depense="2026-03-01")
    apres = await _note(client, employe, 100, "USD", date_depense="2026-07-01")

    assert (avant.json()["taux_applique"], apres.json()["taux_applique"]) == (0.90, 0.95)


async def test_sans_taux_la_soumission_est_refusee_avec_un_message_actionnable(client, db_session, equipe):
    _, employe = equipe
    r = await _note(client, employe, 100, "GBP")
    assert r.status_code == 422 and "Aucun taux de change disponible pour GBP" in r.json()["detail"]


async def test_le_budget_est_verifie_sur_le_montant_converti_pas_sur_le_brut(client, db_session, equipe):
    """Cas ou le verdict DIFFERE entre montant brut et montant converti (sinon le test ne prouverait rien)."""
    _, employe = equipe
    await _taux(db_session, "XAF", 0.0015)
    await _taux(db_session, "GBP", 1.20)
    await _budget(db_session, 500)  # EUR

    # Brut 60000 >> 500 mais converti 90 EUR : DOIT passer sans derogation
    xaf = await _note(client, employe, 60000, "XAF")
    # Brut 450 <= 500 mais converti 540 EUR : DOIT depasser l'enveloppe (motif de derogation exige)
    gbp = await _note(client, employe, 450, "GBP")

    assert xaf.status_code == 201 and xaf.json()["derogation"] is False
    assert gbp.status_code == 422
    assert "540.0 € demandé(s) pour 500.0 € disponible(s)" in gbp.json()["detail"]  # message en devise de reference


async def _escalade_creee(db_session, reponse):
    etapes = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(reponse.json()["id"])))).scalars().all()
    return etapes


async def _approuver_niveau1(client, db_session, reponse, manager):
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(reponse.json()["premiere_etape_id"]), "approuver", manager.id)
    await db_session.commit()
    return await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=_h(manager))


async def test_le_seuil_d_escalade_se_compare_au_montant_converti_pas_au_montant_brut(client, db_session, equipe, emails):
    manager, employe = equipe
    await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    await _taux(db_session, "USD", 0.80)
    await _taux(db_session, "XAF", 0.0015)
    await _taux(db_session, "GBP", 1.20)
    await _budget(db_session, 100000)

    # Brut 560 > 500 mais converti 448 EUR < 500 : PAS d'escalade (l'ancienne comparaison brute l'aurait declenchee)
    usd = await _note(client, employe, 560, "USD")
    # Brut 60000 >> 500 mais converti 90 EUR : PAS d'escalade non plus
    xaf = await _note(client, employe, 60000, "XAF")
    # Brut 450 < 500 mais converti 540 EUR > 500 : escalade (la comparaison brute l'aurait manquee)
    gbp = await _note(client, employe, 450, "GBP")

    resultats = {}
    for nom, r in (("usd", usd), ("xaf", xaf), ("gbp", gbp)):
        d = await _approuver_niveau1(client, db_session, r, manager)
        resultats[nom] = d.json()["statut_global"]

    assert resultats == {"usd": "terminee", "xaf": "terminee", "gbp": "en_cours"}


async def test_le_budget_est_debite_du_montant_converti(client, db_session, equipe, emails):
    manager, employe = equipe
    await _taux(db_session, "USD", 0.90)
    await _budget(db_session, 1000)
    r = await _note(client, employe, 200, "USD")  # 180 EUR

    d = await _approuver_niveau1(client, db_session, r, manager)

    assert d.json()["statut_global"] == "terminee"
    assert await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", 2026) == 820.0  # 1000 - 180, pas 1000 - 200


async def test_un_taux_modifie_apres_coup_ne_change_pas_l_engagement_deja_pris(client, db_session, equipe, emails):
    manager, employe = equipe
    drh = await _u(db_session, RoleUtilisateur.DRH)
    await _taux(db_session, "USD", 0.90)
    await _budget(db_session, 1000)
    r = await _note(client, employe, 200, "USD")  # fige a 180 EUR

    # le taux du meme jour est corrige a 2.0 AVANT la decision
    await client.put("/api/v1/taux-change/", json={"devise": "USD", "taux": 2.0, "date_effet": "2026-01-01"}, headers=_h(drh))
    await _approuver_niveau1(client, db_session, r, manager)

    assert await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", 2026) == 820.0  # toujours 180 : fige


async def test_le_decideur_voit_le_montant_d_origine_et_le_solde_en_devise_de_reference(client, db_session, equipe, emails):
    manager, employe = equipe
    await _taux(db_session, "USD", 0.92)
    await _budget(db_session, 5000)
    r = await _note(client, employe, 800, "USD")
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(r.json()["premiere_etape_id"]), "approuver", manager.id)
    await db_session.commit()

    apercu = (await client.get(f"/api/v1/decisions/{jeton}")).json()

    assert (apercu["resume"]["montant"], apercu["resume"]["devise"], apercu["resume"]["montant_reference"]) == (800.0, "USD", 736.0)
    assert apercu["budget"]["montant_demande"] == 736.0 and apercu["budget"]["devise"] == "EUR"
    corps = emails.call_args_list[0].kwargs["corps_html"]
    assert "800.0 USD (≈ 736.0 €)" in corps                       # e-mail de premiere decision
    assert "Montant demandé : 736.0 €" in corps                   # bloc budget en devise de reference


async def test_une_note_sans_devise_reste_lue_dans_la_devise_de_reference(client, db_session, equipe, emails):
    manager, employe = equipe
    await _budget(db_session, 1000)
    r = await _note(client, employe, 120)  # aucune devise, aucun taux

    assert r.status_code == 201 and (r.json()["devise"], r.json()["taux_applique"], r.json()["montant_reference"]) == ("EUR", 1.0, 120.0)
    assert "120.0 €" in emails.call_args_list[0].kwargs["corps_html"] and "≈" not in emails.call_args_list[0].kwargs["corps_html"]


# --- achats et bon de commande -------------------------------------------------------------

async def test_un_achat_en_devise_est_converti_puis_le_bon_de_commande_reste_dans_la_devise_du_contrat(client, db_session, monkeypatch, emails):
    from app.services import documents

    juriste = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _taux(db_session, "USD", 0.90)
    await _budget(db_session, 5000, exercice=datetime.now(UTC).year)
    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/achats/",
        data={"tiers": "Fournisseur US", "objet": "Licences", "budget_engage": "1000", "devise": "usd"},
        files={"fichier_contrat": ("c.pdf", b"%PDF-1.4 x", "application/pdf")},
    )
    app.dependency_overrides.pop(get_current_user, None)
    assert soumission.status_code == 201
    assert (soumission.json()["devise"], soumission.json()["budget_engage_reference"]) == ("USD", 900.0)

    for personne, action, corps in ((juriste, "approuver", {}), (dg, "signer", {"signature_image_base64": SIGNATURE_PNG})):
        etape = (await db_session.execute(select(EtapeWorkflow).where(
            EtapeWorkflow.demande_id == uuid.UUID(soumission.json()["id"]), EtapeWorkflow.approbateur_attendu_id == personne.id))).scalar_one_or_none()
        if etape is None:
            etape = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(soumission.json()["id"]), EtapeWorkflow.niveau == 2))).scalar_one()
        jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, action, personne.id)
        await db_session.commit()
        await client.post(f"/api/v1/decisions/{jeton}", json=corps, headers=_h(personne))

    assert await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", datetime.now(UTC).year) == 4100.0  # 5000 - 900

    capture = {}

    class FauxHTML:
        def __init__(self, string):
            capture["html"] = string

        def write_pdf(self):
            return b"%PDF"

    monkeypatch.setattr(documents.weasyprint, "HTML", FauxHTML)
    bc = await client.get(f"/api/v1/achats/{soumission.json()['id']}/bon-de-commande", headers=_h(employe))

    assert bc.status_code == 200
    html = capture["html"]
    assert "Total TTC</td><td>1000.00 USD" in html                   # dans la devise du contrat
    assert "Équivalent budgétaire : 900.00 €" in html and "1 USD = 0.9 €" in html


async def test_un_achat_sans_taux_est_refuse(client, db_session):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    app.dependency_overrides[get_current_user] = lambda: employe
    r = await client.post(
        "/api/v1/achats/", data={"tiers": "X", "objet": "Y", "budget_engage": "10", "devise": "JPY"},
        files={"fichier_contrat": ("c.pdf", b"%PDF-1.4 x", "application/pdf")},
    )
    app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 422 and "JPY" in r.json()["detail"]


# --- rappels ----------------------------------------------------------------------------------

def test_les_rappels_montrent_la_devise_d_origine_et_l_equivalent():
    from app.models.demande import Demande
    from app.models.enums import TypeProcessus
    from app.services.rappels import resume_html

    d = Demande(processus=TypeProcessus.NOTES_FRAIS, donnees={"montant": 800.0, "devise": "USD", "montant_reference": 736.0,
                                                              "categorie": "Materiel", "date_depense": "2026-03-01"})
    assert "800.0 USD (≈ 736.0 €)" in resume_html(d)


# --- devise de reference configurable ------------------------------------------------------------

async def test_la_devise_de_reference_est_configurable(db_session, monkeypatch):
    monkeypatch.setattr(devises.settings, "devise_reference", "xaf")
    db_session.add(TauxChange(devise="EUR", taux=655.957, date_effet=date(2026, 1, 1)))
    await db_session.commit()

    identique = await devises.convertir(db_session, 10000.0, "XAF", date(2026, 3, 1))
    en_euro = await devises.convertir(db_session, 500.0, "EUR", date(2026, 3, 1))

    assert (identique.taux, identique.montant_reference) == (1.0, 10000.0)
    assert en_euro.montant_reference == 327978.5
    assert devises.formater(5.0, "XAF") == "5.0 XAF" and devises.devise_reference() == "XAF"
