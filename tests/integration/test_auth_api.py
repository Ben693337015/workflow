"""Test d'intégration - authentification (section 5)."""
from app.core.security import hash_password
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, mot_de_passe="MonMotDePasse123!"):
    utilisateur = Utilisateur(
        email="test@example.com",
        mot_de_passe_hash=hash_password(mot_de_passe),
        nom_complet="Utilisateur Test",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def test_login_avec_les_bons_identifiants_renvoie_des_jetons(client, db_session):
    await _creer_utilisateur(db_session)

    reponse = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "mot_de_passe": "MonMotDePasse123!"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert "access_token" in corps
    assert "refresh_token" in corps
    assert corps["token_type"] == "bearer"


async def test_login_avec_mauvais_mot_de_passe_est_rejete(client, db_session):
    await _creer_utilisateur(db_session)

    reponse = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "mot_de_passe": "MauvaisMotDePasse"},
    )

    assert reponse.status_code == 401


async def test_login_avec_email_inconnu_est_rejete(client, db_session):
    reponse = await client.post(
        "/api/v1/auth/login",
        json={"email": "inconnu@example.com", "mot_de_passe": "peu-importe"},
    )

    assert reponse.status_code == 401


async def test_refresh_avec_un_access_token_a_la_place_du_refresh_est_rejete(client, db_session):
    utilisateur = await _creer_utilisateur(db_session)
    from app.core.security import create_access_token

    reponse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": create_access_token(str(utilisateur.id))},
    )

    assert reponse.status_code == 401


async def test_me_retourne_le_profil_de_lutilisateur_connecte(client, db_session):
    from app.core.dependencies import get_current_user
    from app.main import app

    utilisateur = await _creer_utilisateur(db_session)
    app.dependency_overrides[get_current_user] = lambda: utilisateur

    reponse = await client.get("/api/v1/auth/me")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["email"] == "test@example.com"
    assert corps["role"] == "employe"
    app.dependency_overrides.pop(get_current_user, None)


async def test_me_sans_authentification_est_rejete(client, db_session):
    reponse = await client.get("/api/v1/auth/me")
    assert reponse.status_code == 401


async def test_me_retourne_lutilisateur_connecte(client, db_session):
    from app.core.dependencies import get_current_user
    from app.main import app

    utilisateur = await _creer_utilisateur(db_session)
    app.dependency_overrides[get_current_user] = lambda: utilisateur

    reponse = await client.get("/api/v1/auth/me")

    assert reponse.status_code == 200
    assert reponse.json()["email"] == "test@example.com"
    assert reponse.json()["role"] == "employe"
    app.dependency_overrides.pop(get_current_user, None)


async def test_un_refresh_token_ne_peut_pas_servir_de_jeton_dacces(client, db_session):
    """
    Ecart identifié et corrigé (revue du 15/09) : get_current_user ne
    vérifiait pas le type du jeton - un jeton de rafraîchissement (durée de
    vie longue) pouvait donc être utilisé directement comme jeton d'accès
    sur n'importe quelle route protégée.
    """
    from app.core.security import create_refresh_token

    utilisateur = await _creer_utilisateur(db_session)
    reponse = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {create_refresh_token(str(utilisateur.id))}"}
    )
    assert reponse.status_code == 401


async def test_compte_non_active_ne_peut_pas_se_connecter(client, db_session):
    """
    Ecart identifié et corrigé (revue du 15/09) : un compte créé par le DRH
    via l'invitation (section 5) n'a pas encore de mot de passe - la
    connexion doit être rejetée proprement (401), pas planter sur
    verify_password(..., None).
    """
    utilisateur = Utilisateur(
        email="pas-encore-active@example.com",
        mot_de_passe_hash=None,
        nom_complet="Pas Encore Activé",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    await db_session.commit()

    reponse = await client.post(
        "/api/v1/auth/login",
        json={"email": "pas-encore-active@example.com", "mot_de_passe": "peu-importe"},
    )
    assert reponse.status_code == 401


async def test_flux_complet_invitation_puis_definition_du_mot_de_passe(client, db_session, monkeypatch):
    """
    Rejoue le flux d'invitation de bout en bout : compte créé sans mot de
    passe -> jeton d'invitation généré -> l'employé le consomme pour définir
    son propre mot de passe -> peut ensuite se connecter normalement.
    """
    from unittest.mock import AsyncMock

    from app.models.enums import TypeJetonCompte
    from app.services import jetons_compte

    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.auth.email_service.envoyer_email", mock_email)

    utilisateur = Utilisateur(
        email="nouvel.arrivant@example.com",
        mot_de_passe_hash=None,
        nom_complet="Nouvel Arrivant",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    await db_session.flush()
    jeton = await jetons_compte.generer_jeton_compte(db_session, utilisateur.id, TypeJetonCompte.INVITATION)
    await db_session.commit()

    # Tant que le mot de passe n'est pas défini, la connexion échoue.
    echec = await client.post(
        "/api/v1/auth/login",
        json={"email": "nouvel.arrivant@example.com", "mot_de_passe": "MotDePasse123!"},
    )
    assert echec.status_code == 401

    reponse = await client.post(
        "/api/v1/auth/definir-mot-de-passe",
        json={"jeton": jeton, "mot_de_passe": "MotDePasse123!"},
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert "access_token" in corps and "refresh_token" in corps

    # Le jeton est a usage unique.
    rejeu = await client.post(
        "/api/v1/auth/definir-mot-de-passe",
        json={"jeton": jeton, "mot_de_passe": "AutreMotDePasse123!"},
    )
    assert rejeu.status_code == 401

    connexion = await client.post(
        "/api/v1/auth/login",
        json={"email": "nouvel.arrivant@example.com", "mot_de_passe": "MotDePasse123!"},
    )
    assert connexion.status_code == 200


async def test_definir_mot_de_passe_trop_court_est_rejete(client, db_session):
    """La contrainte de longueur minimale (section 5) vit désormais ici, plus sur la création de compte."""
    from app.models.enums import TypeJetonCompte
    from app.services import jetons_compte

    utilisateur = Utilisateur(
        email="mdp-court@example.com", mot_de_passe_hash=None,
        nom_complet="Test", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    await db_session.flush()
    jeton = await jetons_compte.generer_jeton_compte(db_session, utilisateur.id, TypeJetonCompte.INVITATION)
    await db_session.commit()

    reponse = await client.post(
        "/api/v1/auth/definir-mot-de-passe", json={"jeton": jeton, "mot_de_passe": "court"}
    )
    assert reponse.status_code == 422


async def test_mot_de_passe_oublie_envoie_un_lien_si_le_compte_existe(client, db_session, monkeypatch):
    from unittest.mock import AsyncMock

    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.auth.email_service.envoyer_email", mock_email)

    await _creer_utilisateur(db_session)

    reponse = await client.post("/api/v1/auth/mot-de-passe-oublie", json={"email": "test@example.com"})

    assert reponse.status_code == 202
    mock_email.assert_awaited_once()
    assert mock_email.await_args.kwargs["destinataire"] == "test@example.com"


async def test_mot_de_passe_oublie_ne_revele_pas_si_le_compte_nexiste_pas(client, db_session, monkeypatch):
    """
    Écart évité (revue du 15/09) : une réponse différente selon que l'e-mail
    existe ou non permettrait l'énumération de comptes. Même code, même
    message, dans les deux cas.
    """
    from unittest.mock import AsyncMock

    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.auth.email_service.envoyer_email", mock_email)

    reponse = await client.post("/api/v1/auth/mot-de-passe-oublie", json={"email": "personne@example.com"})

    assert reponse.status_code == 202
    mock_email.assert_not_awaited()
