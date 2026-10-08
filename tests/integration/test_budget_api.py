"""Tests d'integration - enveloppes budgetaires (app/routers/budget.py)."""
from app.core.dependencies import get_current_user
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, email=None):
    utilisateur = Utilisateur(
        email=email or f"{role.value}@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Test",
        service="Ventes",
        role=role,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_drh_peut_creer_une_enveloppe(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH)
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.put(
        "/api/v1/enveloppes-budgetaires/",
        json={"service": "Ventes", "exercice": 2026, "budget_alloue": 5000},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["service"] == "Ventes"
    assert corps["budget_alloue"] == 5000
    assert corps["budget_consomme"] == 0
    assert corps["solde_disponible"] == 5000
    app.dependency_overrides.pop(get_current_user, None)


async def test_redefinir_une_enveloppe_existante_ne_reinitialise_pas_le_consomme(client, db_session):
    """PUT est idempotent sur le service/exercice : met a jour budget_alloue
    sans jamais toucher a budget_consomme (deja engage sur des depenses
    reelles)."""
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH)
    app.dependency_overrides[get_current_user] = lambda: drh

    await client.put(
        "/api/v1/enveloppes-budgetaires/",
        json={"service": "Ventes", "exercice": 2026, "budget_alloue": 1000},
    )

    from app.services.extensions import suivi_budgetaire

    await suivi_budgetaire.consommer_budget(db_session, "Ventes", 2026, 300)
    await db_session.commit()

    reponse = await client.put(
        "/api/v1/enveloppes-budgetaires/",
        json={"service": "Ventes", "exercice": 2026, "budget_alloue": 2000},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["budget_alloue"] == 2000
    assert corps["budget_consomme"] == 300  # inchange
    assert corps["solde_disponible"] == 1700
    app.dependency_overrides.pop(get_current_user, None)


async def test_employe_ne_peut_pas_definir_une_enveloppe(client, db_session):
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.put(
        "/api/v1/enveloppes-budgetaires/",
        json={"service": "Ventes", "exercice": 2026, "budget_alloue": 5000},
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_controleur_de_gestion_peut_lister_les_enveloppes(client, db_session):
    controleur = await _creer_utilisateur(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION)
    app.dependency_overrides[get_current_user] = lambda: controleur

    await client.put(
        "/api/v1/enveloppes-budgetaires/",
        json={"service": "Ventes", "exercice": 2026, "budget_alloue": 5000},
    )
    reponse = await client.get("/api/v1/enveloppes-budgetaires/")

    assert reponse.status_code == 200
    assert len(reponse.json()) == 1
    app.dependency_overrides.pop(get_current_user, None)
