"""
Correction R19 : GET /api/v1/conges/{id} etait ouvert a quiconque connaissait
l'identifiant. Il est desormais reserve au demandeur, a son manager, a la DRH et
aux approbateurs attendus de la demande. Les autres recoivent un 404, pour ne pas
reveler l'existence d'un dossier.
"""
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur
from tests.integration.test_conges_api import _preparer_employe_et_manager


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.conges.email_service.envoyer_email", mock)
    return mock


async def _creer_demande(client, employe, type_conge):
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    assert reponse.status_code == 201
    return reponse.json()["id"]


async def _autre_utilisateur(db_session, email, role):
    utilisateur = Utilisateur(
        email=email, mot_de_passe_hash="hash", nom_complet="Autre", service="Ailleurs", role=role
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_route_sans_authentification_est_refusee(client, db_session):
    employe, _manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    demande_id = await _creer_demande(client, employe, type_conge)
    app.dependency_overrides.pop(get_current_user, None)

    reponse = await client.get(f"/api/v1/conges/{demande_id}")

    assert reponse.status_code == 401


@pytest.mark.parametrize("qui", ["demandeur", "manager", "drh"])
async def test_acces_autorise(client, db_session, qui):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    demande_id = await _creer_demande(client, employe, type_conge)
    if qui == "demandeur":
        lecteur = employe
    elif qui == "manager":
        lecteur = manager
    else:
        lecteur = await _autre_utilisateur(db_session, "drh@example.com", RoleUtilisateur.DRH)
    app.dependency_overrides[get_current_user] = lambda: lecteur

    reponse = await client.get(f"/api/v1/conges/{demande_id}")

    assert reponse.status_code == 200
    assert reponse.json()["id"] == demande_id
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("role", [RoleUtilisateur.EMPLOYE, RoleUtilisateur.MANAGER, RoleUtilisateur.DIRECTION_GENERALE])
async def test_utilisateur_sans_lien_avec_la_demande_recoit_404(client, db_session, role):
    employe, _manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    demande_id = await _creer_demande(client, employe, type_conge)
    curieux = await _autre_utilisateur(db_session, "curieux@example.com", role)
    app.dependency_overrides[get_current_user] = lambda: curieux

    reponse = await client.get(f"/api/v1/conges/{demande_id}")

    assert reponse.status_code == 404
    app.dependency_overrides.pop(get_current_user, None)
