"""
Tests d'integration de l'arbitrage exceptionnel (ecart n°4, section 4.4 du
CDC fonctionnel) : derogation motivee par le demandeur, ou depassement
budgetaire detecte automatiquement - dans les deux cas, detournement vers
un arbitre (notes de frais : Direction financiere seule ; achats : Controleur de gestion, Direction generale en repli),
avec justification d'acceptation obligatoire pour approuver.
"""
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, service="Ventes", email=None):
    utilisateur = Utilisateur(
        email=email or f"{role.value}@example.com",
        mot_de_passe_hash="hash",
        nom_complet=f"Test {role.value}",
        service=service,
        role=role,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def _creer_enveloppe(db_session, service, exercice, budget_alloue):
    enveloppe = EnveloppeBudgetaire(service=service, exercice=exercice, budget_alloue=budget_alloue)
    db_session.add(enveloppe)
    await db_session.commit()
    return enveloppe


def _entete(utilisateur):
    return {"Authorization": f"Bearer {create_access_token(str(utilisateur.id))}"}


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.notes_frais.email_service.envoyer_email", mock)
    monkeypatch.setattr("app.routers.achats.email_service.envoyer_email", mock)
    monkeypatch.setattr("app.routers.decisions.email_service.envoyer_email", mock)
    return mock


async def test_budget_insuffisant_sans_motif_est_rejete(client, db_session):
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={"montant": 500, "categorie": "Matériel", "date_depense": "2026-03-01", "description": "x"},
    )

    assert reponse.status_code == 422
    assert "motif de dérogation" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_budget_insuffisant_avec_motif_route_vers_larbitre_pas_le_manager(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = Utilisateur(
        email="employe-derog@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Employe Derog",
        service="Ventes",
        role=RoleUtilisateur.EMPLOYE,
        manager_id=manager.id,
    )
    db_session.add(employe)
    await db_session.commit()
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 500,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "x",
            "derogation_motivee": True,
            "motif_derogation": "Achat urgent, budget épuisé avant la fin de l'exercice.",
        },
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["derogation"] is True

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow

    etape = (
        await db_session.execute(
            select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(corps["id"]))
        )
    ).scalar_one()
    assert etape.est_derogation is True
    assert etape.approbateur_attendu_id == controleur.id  # pas le manager
    app.dependency_overrides.pop(get_current_user, None)


async def test_derogation_motivee_cochee_meme_avec_budget_suffisant(client, db_session):
    """Le CDC dit bien "coche... OU depassement" - les deux declenchent
    independamment, meme quand le budget est largement suffisant."""
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = Utilisateur(
        email="employe-derog2@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Employe Derog2",
        service="Ventes",
        role=RoleUtilisateur.EMPLOYE,
        manager_id=manager.id,
    )
    db_session.add(employe)
    await db_session.commit()
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100000)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 50,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "x",
            "derogation_motivee": True,
            "motif_derogation": "Cas particulier, je veux un arbitrage direct.",
        },
    )

    assert reponse.status_code == 201
    assert reponse.json()["derogation"] is True
    app.dependency_overrides.pop(get_current_user, None)


async def test_approbation_derogation_sans_justification_est_rejetee(client, db_session):
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 500,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "x",
            "derogation_motivee": True,
            "motif_derogation": "Motif valable.",
        },
    )
    etape_id = soumission.json()["premiere_etape_id"]

    from app.services import decision_tokens

    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape_id), "approuver", controleur.id)
    await db_session.commit()

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=_entete(controleur))

    assert reponse.status_code == 422
    assert "justification" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_approbation_derogation_avec_justification_termine_et_consomme_le_budget_en_negatif(
    client, db_session
):
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 500,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "x",
            "derogation_motivee": True,
            "motif_derogation": "Motif valable.",
        },
    )
    demande_id = soumission.json()["id"]
    etape_id = soumission.json()["premiere_etape_id"]

    from app.services import decision_tokens
    from app.services.extensions import suivi_budgetaire

    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape_id), "approuver", controleur.id)
    await db_session.commit()

    reponse = await client.post(
        f"/api/v1/decisions/{jeton}",
        json={"justification_acceptation": "Exceptionnel, accepté au regard de l'urgence commerciale."},
        headers=_entete(controleur),
    )

    assert reponse.status_code == 200
    assert reponse.json()["statut_global"] == "terminee"

    solde = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", datetime.now(UTC).year)
    assert solde == 100 - 500  # negatif : le depassement a bien ete accepte

    # Journal d'audit : motif et justification "graves" (CDC section 4.4).
    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow

    etape = (
        await db_session.execute(
            select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(demande_id))
        )
    ).scalar_one()
    entree = (
        await db_session.execute(
            select(JournalAudit).where(
                JournalAudit.cible_id == etape.id, JournalAudit.action == "etape_approuvee"
            )
        )
    ).scalar_one()
    assert "urgence commerciale" in entree.details["justification_acceptation"]
    app.dependency_overrides.pop(get_current_user, None)


async def test_refus_derogation_ne_necessite_pas_de_justification(client, db_session):
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 500,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "x",
            "derogation_motivee": True,
            "motif_derogation": "Motif valable.",
        },
    )
    etape_id = soumission.json()["premiere_etape_id"]

    from app.services import decision_tokens
    from app.services.extensions import suivi_budgetaire

    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape_id), "refuser", controleur.id)
    await db_session.commit()

    reponse = await client.post(
        f"/api/v1/decisions/{jeton}",
        json={"commentaire": "Dépassement trop important, refusé."},
        headers=_entete(controleur),
    )

    assert reponse.status_code == 200
    assert reponse.json()["statut_global"] == "refusee"

    solde = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", datetime.now(UTC).year)
    assert solde == 100  # jamais touche
    app.dependency_overrides.pop(get_current_user, None)


async def test_note_de_frais_en_derogation_n_a_jamais_d_autre_arbitre_que_la_direction_financiere(client, db_session):
    """Decision du 07/10 : ni Controleur de gestion, ni repli sur la Direction generale pour une note de frais."""
    await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    await _creer_utilisateur(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)
    # DG et Controleur existent, mais AUCUNE Direction financiere active.

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 500,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "x",
            "derogation_motivee": True,
            "motif_derogation": "Motif valable.",
        },
    )

    assert reponse.status_code == 422
    assert "direction financière" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_la_direction_financiere_est_choisie_meme_si_un_controleur_de_gestion_existe(client, db_session):
    df = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    await _creer_utilisateur(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={"montant": 500, "categorie": "Matériel", "date_depense": "2026-03-01", "description": "x",
              "derogation_motivee": True, "motif_derogation": "Motif valable."},
    )
    assert reponse.status_code == 201

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow

    etape = (
        await db_session.execute(
            select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(reponse.json()["id"]))
        )
    ).scalar_one()
    assert etape.approbateur_attendu_id == df.id and etape.est_derogation is True
    app.dependency_overrides.pop(get_current_user, None)
