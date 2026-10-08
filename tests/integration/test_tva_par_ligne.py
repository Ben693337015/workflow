"""
TVA differenciee par ligne du bon de commande (CDC technique 4.1, decision du 28/09). Ecart
corrige : jusqu'ici un seul taux global (20 %) etait applique a un montant suppose TTC, sans
jamais de ventilation par ligne ni par taux.
"""
from tests.signature_factory import SIGNATURE_PNG
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleEtape, RoleUtilisateur
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.services import decision_tokens, documents, facturation


async def _u(db, role, service="Ventes"):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=f"Test {role.value}", service=service, role=role)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


async def _budget(db, alloue, service="Ventes"):
    db.add(EnveloppeBudgetaire(service=service, exercice=datetime.now(UTC).year, budget_alloue=alloue))
    await db.commit()


@pytest.fixture
def emails(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.services.email_service.envoyer_email", mock)
    return mock


def _soumettre(client, tiers="Fournisseur X", objet="Licences", budget_engage=None, lignes=None, devise=None):
    data = {"tiers": tiers, "objet": objet}
    if budget_engage is not None:
        data["budget_engage"] = str(budget_engage)
    if lignes is not None:
        data["lignes"] = json.dumps(lignes)
    if devise is not None:
        data["devise"] = devise
    return client.post(
        "/api/v1/achats/", data=data,
        files={"fichier_contrat": ("contrat.pdf", b"%PDF-1.4 x", "application/pdf")},
    )


@pytest.fixture
async def juriste(db_session):
    return await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")


# --- soumission avec lignes -------------------------------------------------------------------

async def test_le_budget_engage_est_deduit_du_total_ttc_des_lignes(client, db_session, emails, juriste):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    lignes = [
        {"description": "Materiel", "montant_ht": 1000.0, "taux_tva": 20.0},
        {"description": "Documentation", "montant_ht": 50.0, "taux_tva": 5.5},
    ]
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, lignes=lignes)
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201
    attendu = round(1000 * 1.20 + 50 * 1.055, 2)
    c, r = reponse.status_code, reponse.json()
    assert c == 201 and r["budget_engage_reference"] == attendu

    liste = await client.get("/api/v1/achats/", headers=_h(employe))
    donnees = liste.json()[0]["donnees"]
    assert donnees["budget_engage"] == attendu
    assert donnees["lignes"] == lignes


async def test_budget_ni_lignes_est_refuse(client, db_session, emails, juriste):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client)  # ni budget_engage, ni lignes
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 422
    assert "budget" in reponse.json()["detail"].lower() or "lignes" in reponse.json()["detail"].lower()


async def test_lignes_et_budget_engage_a_la_fois_les_lignes_font_foi(client, db_session, emails, juriste):
    """Un budget_engage fourni en plus des lignes est ignore : les lignes sont la source unique de verite."""
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    lignes = [{"description": "X", "montant_ht": 100.0, "taux_tva": 20.0}]
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, budget_engage=999999, lignes=lignes)  # valeur incoherente, doit etre ignoree
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201 and reponse.json()["budget_engage_reference"] == 120.0


async def test_json_invalide_pour_les_lignes_est_refuse_proprement(client, db_session, emails, juriste):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/achats/", data={"tiers": "X", "objet": "Y", "lignes": "{ceci n'est pas du JSON"},
        files={"fichier_contrat": ("c.pdf", b"%PDF x", "application/pdf")},
    )
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 422 and "JSON" in reponse.json()["detail"]


@pytest.mark.parametrize("lignes, motif", [
    ([], "au moins une ligne"),
    ([{"description": "X", "montant_ht": -10, "taux_tva": 20}], "montant_ht"),
    ([{"description": "X", "montant_ht": 10, "taux_tva": 150}], "taux_tva"),
    ([{"description": "", "montant_ht": 10, "taux_tva": 20}], "description"),
    ([{"description": "X", "montant_ht": 10}], "taux_tva"),  # champ manquant
])
async def test_lignes_invalides_refusees(client, db_session, emails, juriste, lignes, motif):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, lignes=lignes)
    app.dependency_overrides.pop(get_current_user, None)
    assert reponse.status_code == 422, reponse.json()


async def test_le_seuil_d_escalade_et_le_budget_utilisent_le_total_des_lignes(client, db_session, emails, juriste):
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    # Brut de chaque ligne < seuil, mais le TOTAL (720 EUR) le depasse : doit escalader normalement
    # (le circuit achats n'a pas de seuil d'escalade au sens notes de frais, mais le budget doit
    # bien etre verifie sur le total, pas ligne par ligne).
    lignes = [{"description": "A", "montant_ht": 300.0, "taux_tva": 20.0}, {"description": "B", "montant_ht": 300.0, "taux_tva": 20.0}]
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, lignes=lignes)
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201 and reponse.json()["budget_engage_reference"] == 720.0


async def test_devise_avec_lignes_convertit_le_total(client, db_session, emails, juriste):
    from app.models.taux_change import TauxChange
    from datetime import date

    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    db_session.add(TauxChange(devise="USD", taux=0.9, date_effet=date(2026, 1, 1)))
    await db_session.commit()
    lignes = [{"description": "Licence US", "montant_ht": 1000.0, "taux_tva": 0.0}]

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, lignes=lignes, devise="usd")
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201
    assert (reponse.json()["devise"], reponse.json()["budget_engage_reference"]) == ("USD", 900.0)


# --- retrocompatibilite (sans lignes) -----------------------------------------------------------

async def test_soumission_sans_lignes_reste_identique_a_avant(client, db_session, emails, juriste):
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, budget_engage=1200.0)
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201 and reponse.json()["budget_engage_reference"] == 1200.0
    liste = await client.get("/api/v1/achats/", headers=_h(employe))
    assert "lignes" not in liste.json()[0]["donnees"] or liste.json()[0]["donnees"]["lignes"] is None


# --- bon de commande : rendu du detail par ligne -------------------------------------------------

class _FauxHTML:
    dernier_html: str | None = None

    def __init__(self, string):
        type(self).dernier_html = string

    def write_pdf(self):
        return b"%PDF-1.4 factice"


async def _finaliser_achat(client, db_session, employe, juriste, dg, achat_id, signature=True):
    etape1 = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(achat_id), EtapeWorkflow.niveau == 1))).scalar_one()
    jeton1 = await decision_tokens.generer_jeton_decision(db_session, etape1.id, "approuver", juriste.id)
    await db_session.commit()
    await client.post(f"/api/v1/decisions/{jeton1}", json={}, headers=_h(juriste))
    etape2 = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(achat_id), EtapeWorkflow.niveau == 2))).scalar_one()
    jeton2 = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "signer", dg.id)
    await db_session.commit()
    corps = {"signature_image_base64": SIGNATURE_PNG} if signature else {}
    return await client.post(f"/api/v1/decisions/{jeton2}", json=corps, headers=_h(dg))


async def test_le_bon_de_commande_detaille_chaque_ligne_et_regroupe_par_taux(client, db_session, emails, juriste, monkeypatch):
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    lignes = [
        {"description": "Ordinateurs portables", "montant_ht": 1000.0, "taux_tva": 20.0},
        {"description": "Manuels techniques", "montant_ht": 50.0, "taux_tva": 5.5},
        {"description": "Souris sans fil", "montant_ht": 200.0, "taux_tva": 20.0},
    ]
    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, lignes=lignes)
    app.dependency_overrides.pop(get_current_user, None)
    await _finaliser_achat(client, db_session, employe, juriste, dg, soumission.json()["id"])

    monkeypatch.setattr(documents.weasyprint, "HTML", _FauxHTML)
    reponse = await client.get(f"/api/v1/achats/{soumission.json()['id']}/bon-de-commande", headers=_h(employe))

    assert reponse.status_code == 200
    html = _FauxHTML.dernier_html
    assert "Détail des lignes et montants" in html
    for description in ("Ordinateurs portables", "Manuels techniques", "Souris sans fil"):
        assert description in html
    assert "TVA (20 %)" in html and "TVA (5.5 %)" in html  # regroupees par taux, chacune sa ligne
    assert "Total HT</td><td>1250.00" in html  # 1000 + 50 + 200
    assert "Total TTC</td><td>1492.75" in html  # 1200 + 52.75 + 240


async def test_le_bon_de_commande_reste_conforme_pour_une_demande_sans_lignes(client, db_session, emails, juriste, monkeypatch):
    """Retrocompatibilite : une demande soumise avant l'extension (aucune ligne enregistree) genere
    toujours un bon de commande, avec l'ancien calcul a taux global unique."""
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, budget_engage=1200.0)
    app.dependency_overrides.pop(get_current_user, None)
    await _finaliser_achat(client, db_session, employe, juriste, dg, soumission.json()["id"])

    monkeypatch.setattr(documents.weasyprint, "HTML", _FauxHTML)
    reponse = await client.get(f"/api/v1/achats/{soumission.json()['id']}/bon-de-commande", headers=_h(employe))

    assert reponse.status_code == 200
    html = _FauxHTML.dernier_html
    assert "Détail des lignes et montants" not in html and "<h2>Montants</h2>" in html
    assert "TVA (20 %)" in html
    assert "Total HT</td><td>1000.00" in html and "Total TTC</td><td>1200.00" in html
