"""
Tests d'intégration - routes d'administration ajoutées suite à la revue
comparative : types de congé et jours fériés.
"""
from app.core.dependencies import get_current_user
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role):
    utilisateur = Utilisateur(
        email=f"{role.value}@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Test",
        service="RH",
        role=role,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_drh_peut_creer_un_type_de_conge(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH)
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(
        "/api/v1/types-conge/",
        json={"code": "maladie", "nom": "Congé maladie", "taux_acquisition_jours_mois": 0},
    )

    assert reponse.status_code == 201
    assert reponse.json()["code"] == "maladie"
    app.dependency_overrides.pop(get_current_user, None)


async def test_employe_ne_peut_pas_creer_un_type_de_conge(client, db_session):
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/types-conge/",
        json={"code": "maladie", "nom": "Congé maladie"},
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_lister_types_de_conge_ne_retourne_que_les_actifs(client, db_session):
    from app.models.type_conge import TypeConge

    db_session.add(TypeConge(code="actif", nom="Actif", actif=True))
    db_session.add(TypeConge(code="inactif", nom="Inactif", actif=False))
    await db_session.commit()

    reponse = await client.get("/api/v1/types-conge/")

    assert reponse.status_code == 200
    codes = [t["code"] for t in reponse.json()]
    assert "actif" in codes
    assert "inactif" not in codes


async def test_drh_peut_creer_un_jour_ferie(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH)
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(
        "/api/v1/jours-feries/",
        json={"nom": "1er mai", "date": "2026-05-01", "recurrent": True},
    )

    assert reponse.status_code == 201
    assert reponse.json()["recurrent"] is True
    app.dependency_overrides.pop(get_current_user, None)


async def test_manager_ne_peut_pas_creer_un_jour_ferie(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER)
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/jours-feries/",
        json={"nom": "1er mai", "date": "2026-05-01"},
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)
