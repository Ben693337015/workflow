"""
Tests d'intégration - gestion de compte employé par le DRH (écart
identifié suite à la revue comparative avec une référence externe :
création, modification, désactivation/réactivation d'un compte).
"""
import pytest

from app.core.dependencies import get_current_user
from app.core.security import hash_password
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, email="test@example.com"):
    utilisateur = Utilisateur(
        email=email,
        mot_de_passe_hash=hash_password("MotDePasse123!"),
        nom_complet="Test",
        service="RH",
        role=role,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_drh_peut_creer_un_compte_employe(client, db_session, monkeypatch):
    from unittest.mock import AsyncMock

    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.utilisateurs.email_service.envoyer_email", mock_email)

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(
        "/api/v1/utilisateurs/",
        json={
            "email": "nouvel.employe@example.com",
            "nom_complet": "Nouvel Employé",
            "service": "Support",
            "role": "employe",
        },
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["email"] == "nouvel.employe@example.com"
    assert corps["actif"] is True
    # Ecart corrige (revue du 15/09) : plus de mot de passe dans le payload -
    # une invitation est envoyee a la place (voir test dedie plus bas).
    mock_email.assert_awaited_once()
    assert mock_email.await_args.kwargs["destinataire"] == "nouvel.employe@example.com"
    assert "/activer-compte/" in mock_email.await_args.kwargs["corps_html"]
    app.dependency_overrides.pop(get_current_user, None)


# --- Vérification demandée explicitement : la notification d'invitation ET
# l'activation par le lien reçu doivent fonctionner pour TOUS les rôles,
# sans exception - pas seulement "employe" (seul rôle couvert jusqu'ici). ---


@pytest.mark.parametrize(
    "role",
    [
        RoleUtilisateur.EMPLOYE,
        RoleUtilisateur.MANAGER,
        RoleUtilisateur.DRH,
        RoleUtilisateur.DIRECTION_FINANCIERE,
        RoleUtilisateur.SERVICE_JURIDIQUE,
        RoleUtilisateur.DIRECTION_GENERALE,
        RoleUtilisateur.CONTROLEUR_DE_GESTION,
    ],
)
async def test_invitation_et_activation_fonctionnent_pour_tous_les_roles_sans_exception(
    client, db_session, monkeypatch, role
):
    """
    Écart à vérifier explicitement : la notification par e-mail à la
    création d'un compte, puis l'activation via le lien reçu, doivent
    fonctionner identiquement quel que soit le rôle attribué par la DRH -
    employé, manager, DRH ou tout autre rôle du CDC (section 8), sans
    exception ni cas particulier caché dans le code.
    """
    import re
    from unittest.mock import AsyncMock

    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.utilisateurs.email_service.envoyer_email", mock_email)

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, f"drh-{role.value}@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    email_nouveau_compte = f"nouveau-{role.value}@example.com"
    reponse = await client.post(
        "/api/v1/utilisateurs/",
        json={
            "email": email_nouveau_compte,
            "nom_complet": f"Test {role.value}",
            "service": "Support",
            "role": role.value,
        },
    )
    assert reponse.status_code == 201, f"Échec de création pour le rôle {role.value} : {reponse.text}"
    app.dependency_overrides.pop(get_current_user, None)

    # 1. L'e-mail d'invitation part bien, avec le bon destinataire et le bon rôle mentionné.
    mock_email.assert_awaited_once()
    assert mock_email.await_args.kwargs["destinataire"] == email_nouveau_compte
    corps_html = mock_email.await_args.kwargs["corps_html"]
    assert "/activer-compte/" in corps_html
    assert role.value in corps_html

    # 2. Le jeton extrait du lien reçu permet réellement d'activer le compte.
    jeton = re.search(r"/activer-compte/([A-Za-z0-9_\-]+)", corps_html).group(1)
    reponse_activation = await client.post(
        "/api/v1/auth/definir-mot-de-passe",
        json={"jeton": jeton, "mot_de_passe": "MotDePasseTest123!"},
    )
    assert reponse_activation.status_code == 200, (
        f"Échec d'activation pour le rôle {role.value} : {reponse_activation.text}"
    )
    assert "access_token" in reponse_activation.json()

    # 3. Le compte activé peut ensuite se connecter normalement, avec le bon rôle.
    reponse_login = await client.post(
        "/api/v1/auth/login", json={"email": email_nouveau_compte, "mot_de_passe": "MotDePasseTest123!"}
    )
    assert reponse_login.status_code == 200

    jeton_acces = reponse_login.json()["access_token"]
    reponse_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton_acces}"})
    assert reponse_me.status_code == 200
    assert reponse_me.json()["role"] == role.value


async def test_manager_ne_peut_pas_creer_un_compte(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager@example.com")
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/utilisateurs/",
        json={"email": "x@example.com", "nom_complet": "X", "service": "Support", "role": "employe"},
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_creation_avec_email_deja_utilise_est_rejetee(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh2@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    await client.post(
        "/api/v1/utilisateurs/",
        json={"email": "doublon@example.com", "nom_complet": "Premier", "service": "Support", "role": "employe"},
    )
    reponse = await client.post(
        "/api/v1/utilisateurs/",
        json={"email": "doublon@example.com", "nom_complet": "Second", "service": "Support", "role": "employe"},
    )

    assert reponse.status_code == 409
    app.dependency_overrides.pop(get_current_user, None)


async def test_compte_cree_par_le_drh_na_pas_de_mot_de_passe_immediatement_utilisable(client, db_session):
    """
    Ecart corrige (revue du 15/09) : le DRH ne choisit plus le mot de passe
    (voir test_drh_peut_creer_un_compte_employe) - le compte créé ne doit
    donc pas pouvoir se connecter avant que l'employé n'ait suivi son lien
    d'invitation et défini lui-même son mot de passe.
    """
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh3@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    await client.post(
        "/api/v1/utilisateurs/",
        json={"email": "y@example.com", "nom_complet": "Y", "service": "Support", "role": "employe"},
    )
    app.dependency_overrides.pop(get_current_user, None)

    reponse = await client.post(
        "/api/v1/auth/login", json={"email": "y@example.com", "mot_de_passe": "peu-importe"}
    )
    assert reponse.status_code == 401


async def test_creation_avec_manager_inconnu_est_rejetee(client, db_session):
    import uuid

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh4@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(
        "/api/v1/utilisateurs/",
        json={
            "email": "z@example.com", "nom_complet": "Z", "service": "Support", "role": "employe",
            "manager_id": str(uuid.uuid4()),
        },
    )

    assert reponse.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_drh_peut_modifier_un_compte(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh5@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe5@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.patch(
        f"/api/v1/utilisateurs/{employe.id}", json={"service": "Comptabilité"}
    )

    assert reponse.status_code == 200
    assert reponse.json()["service"] == "Comptabilité"
    app.dependency_overrides.pop(get_current_user, None)


async def test_un_utilisateur_ne_peut_pas_etre_son_propre_manager(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh6@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe6@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.patch(
        f"/api/v1/utilisateurs/{employe.id}", json={"manager_id": str(employe.id)}
    )

    assert reponse.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_desactivation_puis_reactivation_dun_compte(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh7@example.com")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "employe7@example.com")
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.post(f"/api/v1/utilisateurs/{employe.id}/desactiver")
    assert reponse.status_code == 200
    assert reponse.json()["actif"] is False

    reponse = await client.post(f"/api/v1/utilisateurs/{employe.id}/reactiver")
    assert reponse.status_code == 200
    assert reponse.json()["actif"] is True
    app.dependency_overrides.pop(get_current_user, None)


async def test_compte_desactive_ne_peut_plus_sauthentifier(client, db_session):
    from app.core.security import create_access_token

    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "a-desactiver@example.com")
    employe.actif = False
    await db_session.commit()

    jeton = create_access_token(str(employe.id))
    reponse = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})

    assert reponse.status_code == 401


async def test_seul_le_drh_voit_la_liste_complete_des_comptes(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager8@example.com")
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.get("/api/v1/utilisateurs/")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


# --- Renvoi d'invitation (écart identifié et corrigé, revue du 16/09,
# suite au test réel de bout en bout : sans ceci, un jeton perdu à l'envoi
# n'avait aucun moyen de rattrapage côté interface). ---------------------


async def test_drh_peut_renvoyer_une_invitation(client, db_session, monkeypatch):
    from unittest.mock import AsyncMock

    from app.models.enums import TypeJetonCompte
    from app.services import jetons_compte

    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.utilisateurs.email_service.envoyer_email", mock_email)

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh-renvoi@example.com")
    non_active = Utilisateur(
        email="non.active@example.com", mot_de_passe_hash=None,
        nom_complet="Non Activé", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(non_active)
    await db_session.flush()
    ancien_jeton = await jetons_compte.generer_jeton_compte(db_session, non_active.id, TypeJetonCompte.INVITATION)
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.post(f"/api/v1/utilisateurs/{non_active.id}/renvoyer-invitation")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["email_envoye"] is True
    assert "/activer-compte/" in corps["lien_activation"]
    mock_email.assert_awaited_once()
    assert mock_email.await_args.kwargs["destinataire"] == "non.active@example.com"

    # L'ancien jeton doit être révoqué (un seul lien actif à la fois, §9.3).
    with pytest.raises(jetons_compte.JetonCompteInvalide, match="révoqué"):
        await jetons_compte.verifier_et_consommer_jeton_compte(db_session, ancien_jeton)

    app.dependency_overrides.pop(get_current_user, None)


async def test_renvoi_dinvitation_signale_lechec_denvoi(client, db_session, monkeypatch):
    """
    Contrairement à la création de compte (best-effort, l'e-mail est
    secondaire), le renvoi EST l'objet de l'action - son échec doit être
    visible, avec le lien fourni en repli plutôt que silencieusement avalé.
    """
    async def _echoue(**kwargs):
        raise RuntimeError("Resend indisponible")

    monkeypatch.setattr("app.routers.utilisateurs.email_service.envoyer_email", _echoue)

    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh-renvoi2@example.com")
    non_active = Utilisateur(
        email="non.active2@example.com", mot_de_passe_hash=None,
        nom_complet="Non Activé", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(non_active)
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.post(f"/api/v1/utilisateurs/{non_active.id}/renvoyer-invitation")

    assert reponse.status_code == 200  # la route elle-meme reussit...
    corps = reponse.json()
    assert corps["email_envoye"] is False  # ...mais signale honnetement l'echec d'envoi
    assert "/activer-compte/" in corps["lien_activation"]  # avec le lien de secours
    app.dependency_overrides.pop(get_current_user, None)


async def test_renvoi_dinvitation_refuse_sur_un_compte_deja_active(client, db_session):
    drh = await _creer_utilisateur(db_session, RoleUtilisateur.DRH, "drh-renvoi3@example.com")
    deja_actif = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, "deja.actif@example.com")

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.post(f"/api/v1/utilisateurs/{deja_actif.id}/renvoyer-invitation")

    assert reponse.status_code == 409
    app.dependency_overrides.pop(get_current_user, None)


async def test_renvoi_dinvitation_est_reserve_au_drh(client, db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, "manager-renvoi@example.com")
    non_active = Utilisateur(
        email="non.active3@example.com", mot_de_passe_hash=None,
        nom_complet="Non Activé", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(non_active)
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.post(f"/api/v1/utilisateurs/{non_active.id}/renvoyer-invitation")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)
