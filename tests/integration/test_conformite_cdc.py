"""
Tests de conformite au CDC issus de l'audit de tracabilite (27/09) : exigences
explicites qui n'etaient couvertes par aucun test ni par aucun code.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.services import decision_tokens


async def _creer(db_session, role, service="Ventes", email=None, manager_id=None):
    u = Utilisateur(
        email=email or f"{role.value}-{uuid.uuid4().hex[:6]}@example.com",
        mot_de_passe_hash="hash", nom_complet=f"Test {role.value}", service=service, role=role, manager_id=manager_id,
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def _enveloppe(db_session, service, exercice, alloue):
    db_session.add(EnveloppeBudgetaire(service=service, exercice=exercice, budget_alloue=alloue))
    await db_session.commit()


@pytest.fixture(autouse=True)
def _mock_email(monkeypatch):
    mock = AsyncMock()
    for module in ("notes_frais", "achats", "decisions"):
        monkeypatch.setattr(f"app.routers.{module}.email_service.envoyer_email", mock)
    return mock


async def _soumettre_note(client, employe, montant, date_depense="2026-03-01"):
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        return await client.post(
            "/api/v1/notes-frais/",
            json={"montant": montant, "categorie": "Matériel", "date_depense": date_depense, "description": "x"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def _jeton(db_session, reponse, approbateur):
    return await decision_tokens.generer_jeton_decision(
        db_session, uuid.UUID(reponse.json()["premiere_etape_id"]), "approuver", approbateur.id
    )


# --- CDC 4.3 : solde budgetaire montre au decideur ---------------------------------

async def test_l_apercu_de_decision_expose_le_solde_budgetaire_d_une_note_de_frais(client, db_session):
    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _enveloppe(db_session, "Ventes", 2026, 1000)
    reponse = await _soumettre_note(client, employe, 300)
    jeton = await _jeton(db_session, reponse, manager)
    await db_session.commit()

    apercu = (await client.get(f"/api/v1/decisions/{jeton}")).json()

    assert apercu["budget"] == {
        "service": "Ventes", "exercice": 2026, "solde_disponible": 1000.0,
        "montant_demande": 300.0, "solde_apres_validation": 700.0, "devise": "EUR",
    }


async def test_l_apercu_montre_un_depassement_sans_le_masquer(client, db_session):
    """Une note qui depasse l'enveloppe (arbitrage par derogation) : le decideur voit le solde negatif."""
    controleur = await _creer(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE)
    await _enveloppe(db_session, "Ventes", 2026, 100)
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={"montant": 500, "categorie": "Matériel", "date_depense": "2026-03-01", "description": "x",
              "derogation_motivee": True, "motif_derogation": "Urgent"},
    )
    app.dependency_overrides.pop(get_current_user, None)
    jeton = await _jeton(db_session, reponse, controleur)
    await db_session.commit()

    apercu = (await client.get(f"/api/v1/decisions/{jeton}")).json()

    assert apercu["budget"]["solde_disponible"] == 100.0
    assert apercu["budget"]["solde_apres_validation"] == -400.0


async def test_le_budget_reflete_les_depenses_deja_validees(client, db_session):
    from app.services.extensions import suivi_budgetaire

    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _enveloppe(db_session, "Ventes", 2026, 1000)
    await suivi_budgetaire.consommer_budget(db_session, "Ventes", 2026, 400)
    await db_session.commit()
    reponse = await _soumettre_note(client, employe, 100)
    jeton = await _jeton(db_session, reponse, manager)
    await db_session.commit()

    budget = (await client.get(f"/api/v1/decisions/{jeton}")).json()["budget"]

    assert budget["solde_disponible"] == 600.0 and budget["solde_apres_validation"] == 500.0


async def test_pas_de_budget_dans_l_apercu_d_une_demande_de_conges(client, db_session):
    from app.models.demande import Demande
    from app.models.enums import RoleEtape, TypeProcessus

    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    demande = Demande(processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id,
                      donnees={"date_debut": "2026-06-01", "date_fin": "2026-06-02"})
    db_session.add(demande)
    await db_session.flush()
    etape = EtapeWorkflow(demande_id=demande.id, niveau=1, role=RoleEtape.APPROBATEUR, approbateur_attendu_id=manager.id)
    db_session.add(etape)
    await db_session.flush()
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", manager.id)
    await db_session.commit()

    assert (await client.get(f"/api/v1/decisions/{jeton}")).json()["budget"] is None


async def test_l_email_de_vote_du_manager_contient_le_solde_budgetaire(client, db_session, _mock_email):
    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _enveloppe(db_session, "Ventes", 2026, 1000)

    await _soumettre_note(client, employe, 300)

    corps = _mock_email.call_args.kwargs["corps_html"]
    assert "Enveloppe suffisante" in corps
    assert "Solde disponible : 1000.0 €" in corps and "Solde après validation : 700.0 €" in corps
    assert "#067647" in corps  # vert : l'enveloppe suffit


async def test_l_email_signale_visuellement_un_depassement(client, db_session, _mock_email):
    await _creer(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE)
    await _enveloppe(db_session, "Ventes", 2026, 100)
    app.dependency_overrides[get_current_user] = lambda: employe
    await client.post(
        "/api/v1/notes-frais/",
        json={"montant": 500, "categorie": "Matériel", "date_depense": "2026-03-01", "description": "x",
              "derogation_motivee": True, "motif_derogation": "Urgent"},
    )
    app.dependency_overrides.pop(get_current_user, None)

    corps = _mock_email.call_args.kwargs["corps_html"]
    assert "Dépassement de l'enveloppe" in corps and "#B42318" in corps  # rouge


async def test_l_email_d_escalade_vers_la_direction_financiere_contient_aussi_le_solde(client, db_session, _mock_email):
    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    await _creer(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _enveloppe(db_session, "Ventes", 2026, 5000)
    reponse = await _soumettre_note(client, employe, 800)  # > seuil de 500 : escalade attendue
    jeton = await _jeton(db_session, reponse, manager)
    await db_session.commit()
    _mock_email.reset_mock()

    decision = await client.post(
        f"/api/v1/decisions/{jeton}", json={},
        headers={"Authorization": f"Bearer {create_access_token(str(manager.id))}"},
    )

    assert decision.status_code == 200 and decision.json()["statut_global"] == "en_cours"
    corps = " ".join(a.kwargs["corps_html"] for a in _mock_email.call_args_list)
    assert "Solde après validation : 4200.0 €" in corps


# --- CDC 2.1 : coherence chronologique des dates ------------------------------------

async def test_une_note_de_frais_datee_du_futur_est_refusee(client, db_session):
    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    demain = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    reponse = await _soumettre_note(client, employe, 50, date_depense=demain)

    assert reponse.status_code == 422
    assert "futur" in str(reponse.json()).lower()


async def test_une_note_de_frais_datee_d_aujourd_hui_est_acceptee(client, db_session):
    manager = await _creer(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _enveloppe(db_session, "Ventes", datetime.now(UTC).year, 1000)

    reponse = await _soumettre_note(client, employe, 50, date_depense=datetime.now(UTC).date().isoformat())

    assert reponse.status_code == 201
