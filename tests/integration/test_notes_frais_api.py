"""
Tests d'integration du processus "Notes de frais" (section 3 / 7 / 11 du
CDC technique) : suivi budgetaire (verrou synchrone avant soumission) et
routage conditionnel sur le montant (escalade vers la Direction financiere
au-dela du seuil configure, app/services/routing_engine.py).
"""
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur

SEUIL = 500.00  # Settings.notes_frais_seuil_direction_financiere (valeur par defaut)


async def _creer_utilisateur(db_session, role, manager_id=None, email=None, service="Support", actif=True):
    utilisateur = Utilisateur(
        email=email or f"{role.value}-{manager_id}@example.com",
        mot_de_passe_hash="hash",
        nom_complet=f"Test {role.value}",
        service=service,
        role=role,
        manager_id=manager_id,
        actif=actif,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def _creer_enveloppe(db_session, service, exercice, budget_alloue):
    enveloppe = EnveloppeBudgetaire(service=service, exercice=exercice, budget_alloue=budget_alloue)
    db_session.add(enveloppe)
    await db_session.commit()
    return enveloppe


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    """Evite tout appel reseau reel vers Resend pendant les tests (2 modules l'appellent)."""
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.notes_frais.email_service.envoyer_email", mock)
    monkeypatch.setattr("app.routers.decisions.email_service.envoyer_email", mock)
    return mock


async def test_soumission_bloquee_si_budget_insuffisant(client, db_session):
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    employe.manager_id = manager.id
    await db_session.commit()
    await _creer_enveloppe(db_session, "Ventes", 2026, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 150,
            "categorie": "Transport",
            "date_depense": "2026-03-01",
            "description": "Billet de train",
        },
    )

    assert reponse.status_code == 422
    assert "budget" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_sans_manager_est_rejetee(client, db_session):
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes", manager_id=None)
    await _creer_enveloppe(db_session, "Ventes", 2026, budget_alloue=10000)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={"montant": 50, "categorie": "Repas", "date_depense": "2026-03-01", "description": "Déjeuner client"},
    )

    assert reponse.status_code == 422
    assert "manager" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_sous_le_seuil_une_seule_approbation_termine_et_consomme_le_budget(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes", manager_id=manager.id)
    await _creer_enveloppe(db_session, "Ventes", 2026, budget_alloue=1000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": 200,
            "categorie": "Transport",
            "date_depense": "2026-03-01",
            "description": "Billet de train",
        },
    )
    assert soumission.status_code == 201
    assert soumission.json()["statut_global"] == "en_cours"

    import uuid

    from app.services import decision_tokens

    etape_id = soumission.json()["premiere_etape_id"]
    jeton_test = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape_id), "approuver", manager.id)
    await db_session.commit()

    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    decision = await client.post(f"/api/v1/decisions/{jeton_test}", json={}, headers=entete)
    assert decision.status_code == 200
    assert decision.json()["statut_global"] == "terminee"

    from app.services.extensions import suivi_budgetaire

    solde = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", 2026)
    assert solde == 800  # 1000 - 200
    app.dependency_overrides.pop(get_current_user, None)


async def test_au_dela_du_seuil_escalade_vers_direction_financiere_puis_approuve(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    df = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes", manager_id=manager.id)
    await _creer_enveloppe(db_session, "Ventes", 2026, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": SEUIL + 300,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "Ordinateur portable",
        },
    )
    assert soumission.status_code == 201
    demande_id = soumission.json()["id"]
    etape1_id = soumission.json()["premiere_etape_id"]

    import uuid

    from app.services import decision_tokens
    from app.services.extensions import suivi_budgetaire

    jeton_manager = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape1_id), "approuver", manager.id)
    await db_session.commit()
    entete_manager = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    decision1 = await client.post(f"/api/v1/decisions/{jeton_manager}", json={}, headers=entete_manager)
    assert decision1.status_code == 200
    assert decision1.json()["statut_global"] == "en_cours"

    solde_avant_df = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", 2026)
    assert solde_avant_df == 5000

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow

    resultat = await db_session.execute(
        select(EtapeWorkflow).where(
            EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
        )
    )
    etape2 = resultat.scalar_one()
    assert str(etape2.approbateur_attendu_id) == str(df.id)

    jeton_df = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "approuver", df.id)
    await db_session.commit()
    entete_df = {"Authorization": f"Bearer {create_access_token(str(df.id))}"}
    decision2 = await client.post(f"/api/v1/decisions/{jeton_df}", json={}, headers=entete_df)
    assert decision2.status_code == 200
    assert decision2.json()["statut_global"] == "terminee"

    solde_apres = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", 2026)
    assert solde_apres == 5000 - (SEUIL + 300)
    app.dependency_overrides.pop(get_current_user, None)


async def test_refus_par_le_manager_termine_immediatement_sans_escalade_ni_budget(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes", manager_id=manager.id)
    await _creer_enveloppe(db_session, "Ventes", 2026, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": SEUIL + 300,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "Ordinateur portable",
        },
    )
    etape1_id = soumission.json()["premiere_etape_id"]

    import uuid

    from app.services import decision_tokens
    from app.services.extensions import suivi_budgetaire

    jeton_refus = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape1_id), "refuser", manager.id)
    await db_session.commit()
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    decision = await client.post(
        f"/api/v1/decisions/{jeton_refus}", json={"commentaire": "Dépense non justifiée"}, headers=entete
    )
    assert decision.status_code == 200
    assert decision.json()["statut_global"] == "refusee"

    solde = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", 2026)
    assert solde == 5000
    app.dependency_overrides.pop(get_current_user, None)


async def test_escalade_sans_direction_financiere_active_renvoie_une_erreur_propre(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes", manager_id=manager.id)
    await _creer_enveloppe(db_session, "Ventes", 2026, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/notes-frais/",
        json={
            "montant": SEUIL + 300,
            "categorie": "Matériel",
            "date_depense": "2026-03-01",
            "description": "Ordinateur portable",
        },
    )
    etape1_id = soumission.json()["premiere_etape_id"]

    import uuid

    from app.services import decision_tokens

    jeton_manager = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape1_id), "approuver", manager.id)
    await db_session.commit()
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    decision = await client.post(f"/api/v1/decisions/{jeton_manager}", json={}, headers=entete)

    assert decision.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_email_a_l_approbateur_echappe_le_nom_et_le_service_du_demandeur(client, db_session, _mock_envoi_email):
    """Nom et service sont saisis par un administrateur : dans le corps HTML de l'e-mail ils sont échappés,
    jamais injectés tels quels (balise fermante, script...). Vaut pour le circuit standard ET la dérogation."""
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, service="Ventes")
    employe = await _creer_utilisateur(
        db_session, RoleUtilisateur.EMPLOYE, service="R&D <i>x</i>", manager_id=manager.id, email="inj@example.com"
    )
    employe.nom_complet = "<script>alert(1)</script>Eve"
    await db_session.commit()
    await _creer_enveloppe(db_session, "R&D <i>x</i>", 2026, budget_alloue=1000)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/notes-frais/",
        json={"montant": 50, "categorie": "Repas", "date_depense": "2026-03-01", "description": "Déjeuner"},
    )
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201
    corps = _mock_envoi_email.await_args.kwargs["corps_html"]
    assert "<script>" not in corps and "<i>x</i>" not in corps
    assert "&lt;script&gt;" in corps and "R&amp;D" in corps
