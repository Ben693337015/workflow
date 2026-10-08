"""
Tests d'intégration - définition du solde de congés d'un employé, par
type de congé, par la DRH.

Écart identifié (revue du 17/09) : jusqu'ici, rien ne permettait à la DRH
de définir le solde d'un employé - le seul moyen était une intervention
manuelle en base (script de seed). Sans cette route, aucun employé ne
pouvait jamais soumettre de demande de congé sur un déploiement réel : le
verrou RH (§11) traite un solde absent comme 0 jour disponible.
"""
from app.core.dependencies import get_current_user
from app.core.security import hash_password
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, email="test@example.com"):
    utilisateur = Utilisateur(
        email=email, mot_de_passe_hash=hash_password("MotDePasse123!"),
        nom_complet="Test", service="Support", role=role,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def _creer_type_conge(db_session, code="conge_paye"):
    type_conge = TypeConge(code=code, nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.commit()
    return type_conge


async def test_drh_peut_definir_le_solde_initial_dun_employe(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh1@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe1@example.com")
    type_conge = await _creer_type_conge(db_session)

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": str(type_conge.id), "exercice": 2026, "jours_acquis": 25},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["jours_acquis"] == 25
    assert corps["jours_pris"] == 0
    assert corps["solde_jours"] == 25
    app.dependency_overrides.pop(get_current_user, None)


async def test_modifier_un_solde_existant_preserve_les_jours_deja_pris(client, db_session):
    """
    Écart évité (revue du 17/09) : une modification du solde ne doit
    jamais écraser silencieusement les jours déjà consommés - seul l'écart
    entre l'ancien et le nouveau nombre de jours acquis doit être répercuté.
    """
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh2@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe2@example.com")
    type_conge = await _creer_type_conge(db_session)
    db_session.add(SoldeConges(
        utilisateur_id=employe.id, type_conge_id=type_conge.id, exercice=2026,
        jours_acquis=20, jours_pris=5, solde_jours=15,
    ))
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: drh
    # La DRH porte l'acquisition annuelle de 20 à 25 jours (+5).
    reponse = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": str(type_conge.id), "exercice": 2026, "jours_acquis": 25},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["jours_pris"] == 5  # inchangé
    assert corps["solde_jours"] == 20  # 15 + (25-20) = 20, pas 25
    app.dependency_overrides.pop(get_current_user, None)


async def test_jours_acquis_negatifs_sont_rejetes(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh3@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe3@example.com")
    type_conge = await _creer_type_conge(db_session)

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": str(type_conge.id), "exercice": 2026, "jours_acquis": -5},
    )

    assert reponse.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_manager_ne_peut_pas_definir_un_solde(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager1@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe4@example.com")
    type_conge = await _creer_type_conge(db_session)

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": str(type_conge.id), "exercice": 2026, "jours_acquis": 25},
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_definir_un_solde_pour_un_type_de_conge_inconnu_est_rejete(client, db_session):
    import uuid

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh4@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe5@example.com")

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": str(uuid.uuid4()), "exercice": 2026, "jours_acquis": 25},
    )

    assert reponse.status_code == 404
    app.dependency_overrides.pop(get_current_user, None)


async def test_employe_peut_consulter_son_propre_solde_mais_pas_celui_dun_autre(client, db_session):
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe6@example.com")
    autre_employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe7@example.com")
    type_conge = await _creer_type_conge(db_session)
    db_session.add(SoldeConges(
        utilisateur_id=employe.id, type_conge_id=type_conge.id, exercice=2026,
        jours_acquis=15, jours_pris=0, solde_jours=15,
    ))
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse_soi = await client.get(f"/api/v1/utilisateurs/{employe.id}/soldes-conges")
    assert reponse_soi.status_code == 200
    assert len(reponse_soi.json()) == 1

    reponse_autre = await client.get(f"/api/v1/utilisateurs/{autre_employe.id}/soldes-conges")
    assert reponse_autre.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_de_conge_fonctionne_apres_definition_du_solde_par_la_drh(client, db_session):
    """
    Test de bout en bout du scénario réel décrit par l'utilisateur :
    la DRH crée le type de congé, définit le solde, puis l'employé peut
    réellement soumettre une demande - sans aucune intervention manuelle
    en base entre les deux étapes.
    """
    from app.models.user import Utilisateur as _U

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh5@example.com")
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager2@example.com")
    employe = _U(
        email="employe8@example.com", mot_de_passe_hash=hash_password("x"),
        nom_complet="Employé Test", service="Support", role=RoleUtilisateur.EMPLOYE, manager_id=manager.id,
    )
    db_session.add(employe)
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: drh
    creation_type = await client.post(
        "/api/v1/types-conge/", json={"code": "conge_paye_e2e", "nom": "Congé payé", "taux_acquisition_jours_mois": 2.5}
    )
    assert creation_type.status_code == 201
    type_conge_id = creation_type.json()["id"]

    definition_solde = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": type_conge_id, "exercice": 2026, "jours_acquis": 25},
    )
    assert definition_solde.status_code == 200
    app.dependency_overrides.pop(get_current_user, None)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": type_conge_id, "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    assert soumission.status_code == 201
    assert soumission.json()["nombre_jours"] == 3
    app.dependency_overrides.pop(get_current_user, None)
