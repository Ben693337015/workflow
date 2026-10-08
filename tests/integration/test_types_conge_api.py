"""
Tests d'intégration - gestion des types de congé par le DRH.

Écart identifié (revue du 17/09) : aucun test dédié n'existait pour ce
routeur avant cette date, malgré son rôle central (le formulaire de
demande de congé dépend entièrement de la liste des types actifs).
"""
from app.core.dependencies import get_current_user
from app.core.security import hash_password
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, email="test@example.com"):
    utilisateur = Utilisateur(
        email=email, mot_de_passe_hash=hash_password("MotDePasse123!"),
        nom_complet="Test", service="RH", role=role,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_drh_peut_creer_un_type_de_conge(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh1@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(
        "/api/v1/types-conge/",
        json={"code": "conge_paye", "nom": "Congé payé", "taux_acquisition_jours_mois": 2.5},
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["code"] == "conge_paye"
    assert corps["actif"] is True
    app.dependency_overrides.pop(get_current_user, None)


async def test_manager_ne_peut_pas_creer_un_type_de_conge(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager1@example.com")
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/types-conge/", json={"code": "conge_paye", "nom": "Congé payé"}
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_creation_avec_code_deja_utilise_est_rejetee(client, db_session):
    """Écart identifié et corrigé (revue du 17/09) : aucune vérification d'unicité applicative avant cette étape."""
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh2@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    await client.post("/api/v1/types-conge/", json={"code": "maladie", "nom": "Maladie"})
    reponse = await client.post("/api/v1/types-conge/", json={"code": "maladie", "nom": "Maladie (doublon)"})

    assert reponse.status_code == 409
    app.dependency_overrides.pop(get_current_user, None)


async def test_liste_publique_nexpose_que_les_types_actifs(client, db_session):
    db_session.add_all([
        TypeConge(code="actif1", nom="Actif", taux_acquisition_jours_mois=2.5, actif=True),
        TypeConge(code="inactif1", nom="Inactif", taux_acquisition_jours_mois=0, actif=False),
    ])
    await db_session.commit()

    reponse = await client.get("/api/v1/types-conge/")

    assert reponse.status_code == 200
    codes = [t["code"] for t in reponse.json()]
    assert "actif1" in codes
    assert "inactif1" not in codes


async def test_drh_peut_voir_les_types_inactifs_avec_le_parametre(client, db_session):
    db_session.add(TypeConge(code="inactif2", nom="Inactif", taux_acquisition_jours_mois=0, actif=False))
    await db_session.commit()

    reponse = await client.get("/api/v1/types-conge/?inclure_inactifs=true")

    assert reponse.status_code == 200
    codes = [t["code"] for t in reponse.json()]
    assert "inactif2" in codes


async def test_drh_peut_desactiver_puis_reactiver_un_type_de_conge(client, db_session):
    """
    Écart identifié (revue du 17/09) : "supprimer un type de congé" -
    implémenté en désactivation (soft-delete) pour préserver l'intégrité
    des demandes et soldes déjà existants qui le référencent.
    """
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh3@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    creation = await client.post("/api/v1/types-conge/", json={"code": "sans_solde", "nom": "Sans solde"})
    type_id = creation.json()["id"]

    reponse_desact = await client.post(f"/api/v1/types-conge/{type_id}/desactiver")
    assert reponse_desact.status_code == 200
    assert reponse_desact.json()["actif"] is False

    liste = await client.get("/api/v1/types-conge/")
    assert "sans_solde" not in [t["code"] for t in liste.json()]

    reponse_react = await client.post(f"/api/v1/types-conge/{type_id}/reactiver")
    assert reponse_react.status_code == 200
    assert reponse_react.json()["actif"] is True

    liste2 = await client.get("/api/v1/types-conge/")
    assert "sans_solde" in [t["code"] for t in liste2.json()]
    app.dependency_overrides.pop(get_current_user, None)


async def test_manager_ne_peut_pas_desactiver_un_type_de_conge(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager2@example.com")
    type_conge = TypeConge(code="a_proteger", nom="À protéger", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.post(f"/api/v1/types-conge/{type_conge.id}/desactiver")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_desactivation_dun_type_inconnu_est_rejetee(client, db_session):
    import uuid

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh4@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(f"/api/v1/types-conge/{uuid.uuid4()}/desactiver")

    assert reponse.status_code == 404
    app.dependency_overrides.pop(get_current_user, None)
