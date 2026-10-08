"""
Tests d'intégration - liste des utilisateurs pour la régularisation
(écart identifié : nécessaire pour l'écran de régularisation du frontend).
"""
from app.core.dependencies import get_current_user
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, manager_id=None, email=None):
    utilisateur = Utilisateur(
        email=email or f"{role.value}-{manager_id}@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Test",
        service="Support",
        role=role,
        manager_id=manager_id,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_manager_voit_ses_rattaches_directs_et_lui_meme(client, db_session):
    """
    Écart corrigé (26/09) : le manager doit aussi apparaître dans sa propre
    liste (voir docstring de la route) - sinon aucun moyen de se
    sélectionner pour une auto-régularisation.
    """
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, email="manager@example.com")
    autre_manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, email="autre-manager@example.com")
    rattache = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id, email="rattache@example.com")
    await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, manager_id=autre_manager.id, email="pas-rattache@example.com")

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.get("/api/v1/utilisateurs/mon-equipe")

    assert reponse.status_code == 200
    emails = {u["email"] for u in reponse.json()}
    assert emails == {rattache.email, manager.email}
    app.dependency_overrides.pop(get_current_user, None)


async def test_manager_sans_aucun_manager_associe_se_voit_lui_meme(client, db_session):
    """
    Scénario exact de la demande : un manager sans manager_id (personne
    au-dessus de lui dans la hiérarchie, donc personne d'autre en mesure de
    décider pour lui via le circuit normal) doit pouvoir se sélectionner
    lui-même pour se régulariser, malgré manager_id=None.
    """
    manager_sans_hierarchie = await _creer_utilisateur(
        db_session, RoleUtilisateur.MANAGER, manager_id=None, email="chef-sans-chef@example.com"
    )

    app.dependency_overrides[get_current_user] = lambda: manager_sans_hierarchie
    reponse = await client.get("/api/v1/utilisateurs/mon-equipe")

    assert reponse.status_code == 200
    emails = [u["email"] for u in reponse.json()]
    assert emails == [manager_sans_hierarchie.email]
    app.dependency_overrides.pop(get_current_user, None)


async def test_drh_voit_tous_les_employes_actifs(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, email="drh@example.com")
    await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, email="e1@example.com")
    await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, email="e2@example.com")

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.get("/api/v1/utilisateurs/mon-equipe")

    assert reponse.status_code == 200
    assert len(reponse.json()) == 3  # drh + e1 + e2
    app.dependency_overrides.pop(get_current_user, None)


async def test_employe_ne_peut_pas_lister_une_equipe(client, db_session):
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, email="employe@example.com")

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.get("/api/v1/utilisateurs/mon-equipe")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)
