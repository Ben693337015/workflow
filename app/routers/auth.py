"""Routes d'authentification (section 5)."""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.enums import TypeJetonCompte
from app.models.user import Utilisateur
from app.schemas.auth import (
    DefinirMotDePasseRequest,
    LoginRequest,
    MotDePasseOublieRequest,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.user import UtilisateurRead
from app.services import audit, email_gabarit as g, email_service, jetons_compte

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()


def _en_utc(valeur: datetime) -> datetime:
    return valeur.astimezone(UTC) if valeur.tzinfo else valeur.replace(tzinfo=UTC)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Connexion e-mail + mot de passe, avec limitation des tentatives (R9, CDC section 5).

    Apres `connexion_max_tentatives` echecs consecutifs sur un compte existant, le compte est verrouille
    `connexion_duree_verrouillage_minutes` minutes : pendant ce temps, meme le BON mot de passe est refuse
    (sinon le verrou n'arreterait pas une attaque par dictionnaire). Le compteur est incremente par un
    UPDATE atomique cote base, pour que des tentatives simultanees ne puissent pas en perdre.

    Limite connue et assumee : un compte verrouille repond 429 alors qu'un e-mail inconnu repond
    toujours 401 ; apres plusieurs essais, cela revele l'existence du compte. C'est le compromis usuel
    d'un verrouillage par compte ; la reinitialisation du mot de passe (mot de passe oublie) leve le verrou.
    """
    # populate_existing : le compteur et le verrou sont modifies par des UPDATE directs ; on relit donc
    # toujours l'etat reel en base plutot qu'une copie eventuellement perimee en memoire.
    resultat = await db.execute(
        select(Utilisateur).where(Utilisateur.email == payload.email).execution_options(populate_existing=True)
    )
    utilisateur = resultat.scalar_one_or_none()
    maintenant = datetime.now(UTC)

    if utilisateur is not None and utilisateur.verrouille_jusqua is not None:
        fin = _en_utc(utilisateur.verrouille_jusqua)
        if fin > maintenant:
            secondes = max(int((fin - maintenant).total_seconds()), 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives de connexion. Réessayez dans quelques minutes.",
                headers={"Retry-After": str(secondes)},
            )

    mot_de_passe_valide = (
        utilisateur is not None
        and utilisateur.mot_de_passe_hash is not None
        and verify_password(payload.mot_de_passe, utilisateur.mot_de_passe_hash)
    )
    if not mot_de_passe_valide:
        # Seuls les comptes existants et deja actives comptent les echecs (un compte jamais active n'a pas
        # de mot de passe a deviner).
        if utilisateur is not None and utilisateur.mot_de_passe_hash is not None:
            await _enregistrer_echec(db, utilisateur, maintenant)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides.")
    if not utilisateur.actif:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Compte desactive.")

    await db.execute(
        update(Utilisateur)
        .where(Utilisateur.id == utilisateur.id)
        .values(tentatives_echouees=0, verrouille_jusqua=None, dernier_login_le=maintenant)
        .execution_options(synchronize_session=False)
    )
    await audit.consigner(
        db, action="connexion_reussie", acteur_id=utilisateur.id, cible_type="utilisateur",
        cible_id=utilisateur.id, details={},
    )
    await db.commit()

    sujet = str(utilisateur.id)
    return TokenResponse(
        access_token=create_access_token(sujet),
        refresh_token=create_refresh_token(sujet),
    )


async def _enregistrer_echec(db: AsyncSession, utilisateur: Utilisateur, maintenant: datetime) -> None:
    """Incremente le compteur (atomique), verrouille le compte au seuil, trace, et VALIDE : la route qui
    l'appelle leve ensuite une 401, et un rollback implicite effacerait sinon le compteur."""
    resultat = await db.execute(
        update(Utilisateur)
        .where(Utilisateur.id == utilisateur.id)
        .values(tentatives_echouees=Utilisateur.tentatives_echouees + 1)
        .returning(Utilisateur.tentatives_echouees)
        .execution_options(synchronize_session=False)
    )
    tentatives = resultat.scalar_one()
    await audit.consigner(
        db, action="connexion_echouee", acteur_id=utilisateur.id, cible_type="utilisateur",
        cible_id=utilisateur.id, details={"tentatives": tentatives},
    )
    if tentatives >= settings.connexion_max_tentatives:
        fin = maintenant + timedelta(minutes=settings.connexion_duree_verrouillage_minutes)
        await db.execute(
            update(Utilisateur)
            .where(Utilisateur.id == utilisateur.id)
            .values(tentatives_echouees=0, verrouille_jusqua=fin)
            .execution_options(synchronize_session=False)
        )
        await audit.consigner(
            db, action="compte_verrouille", acteur_id=utilisateur.id, cible_type="utilisateur",
            cible_id=utilisateur.id, details={"jusqua": fin.isoformat()},
        )
    await db.commit()


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        contenu = decode_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if contenu.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Le jeton fourni n'est pas un jeton de rafraichissement.",
        )

    utilisateur = await db.get(Utilisateur, uuid.UUID(contenu["sub"]))
    if utilisateur is None or not utilisateur.actif:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable.")

    sujet = str(utilisateur.id)
    return TokenResponse(
        access_token=create_access_token(sujet),
        refresh_token=create_refresh_token(sujet),
    )


@router.get("/me", response_model=UtilisateurRead)
async def qui_suis_je(current_user: Utilisateur = Depends(get_current_user)):
    """
    Nécessaire pour le frontend (écart identifié) : le JWT ne porte que
    l'identifiant utilisateur (section 5), pas son rôle ni son e-mail -
    indispensable pourtant pour adapter l'interface (afficher ou non les
    écrans de régularisation et d'administration selon le rôle).
    """
    return current_user


@router.post("/mot-de-passe-oublie", status_code=status.HTTP_202_ACCEPTED)
async def mot_de_passe_oublie(payload: MotDePasseOublieRequest, db: AsyncSession = Depends(get_db)):
    """
    Ecart corrige (revue du 15/09) : mecanisme explicitement exige par le
    CDC (section 5), absent avant cette date.

    Reponse volontairement identique (202, aucun detail) que l'e-mail
    corresponde ou non à un compte : une reponse differente reveillerait
    a un attaquant quels e-mails sont enregistres sur la plateforme
    (enumeration de comptes).
    """
    resultat = await db.execute(select(Utilisateur).where(Utilisateur.email == payload.email))
    utilisateur = resultat.scalar_one_or_none()

    if utilisateur is not None and utilisateur.actif:
        # Ecart corrige (revue du 16/09) : un seul jeton de reinitialisation
        # actif a la fois (§9.3) - une demande repetee ne doit pas laisser
        # trainer plusieurs liens valides simultanement.
        await jetons_compte.revoquer_jetons_actifs(db, utilisateur.id, TypeJetonCompte.REINITIALISATION)
        jeton = await jetons_compte.generer_jeton_compte(db, utilisateur.id, TypeJetonCompte.REINITIALISATION)
        await db.commit()
        try:
            await email_service.envoyer_email(
                destinataire=utilisateur.email,
                sujet="🔑 Réinitialisation de votre mot de passe",
                corps_html=(
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        "Vous avez demandé à choisir un nouveau mot de passe. Pas de souci, cela ne prend qu'un instant ✨"
                    )
                    + g.boutons(
                        ("Choisir un nouveau mot de passe",
                         f"{settings.frontend_base_url}/reinitialiser-mot-de-passe/{jeton}", "primaire"),
                    )
                    + g.note("⏳ Ce lien est valable 2 heures et ne peut servir qu'une seule fois.")
                    + g.note("🛡️ Vous n'êtes pas à l'origine de cette demande ? Ignorez simplement ce message : votre mot de passe actuel reste inchangé.")
                ),
            )
        except Exception:
            pass  # section 13.4 : ne doit jamais faire echouer la reponse

    return {"detail": "Si un compte existe pour cet e-mail, un lien de réinitialisation a été envoyé."}


@router.post("/definir-mot-de-passe", response_model=TokenResponse)
async def definir_mot_de_passe(payload: DefinirMotDePasseRequest, db: AsyncSession = Depends(get_db)):
    """
    Route unique pour les deux usages du jeton de compte (section 5) :
    activation d'un compte fraîchement créé par le DRH (invitation), ou
    réinitialisation après un mot de passe oublié - dans les deux cas,
    l'employé choisit lui-même son mot de passe, jamais le DRH.

    Connecte immédiatement l'utilisateur (renvoie des jetons de session) une
    fois le mot de passe défini, pour lui éviter une étape de connexion
    supplémentaire juste après avoir cliqué le lien.
    """
    try:
        jeton_ligne = await jetons_compte.verifier_et_consommer_jeton_compte(db, payload.jeton)
    except jetons_compte.JetonCompteInvalide as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    utilisateur = await db.get(Utilisateur, jeton_ligne.utilisateur_id)
    if utilisateur is None or not utilisateur.actif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")

    # Le proprietaire du compte vient de prouver son identite par e-mail : le verrou est leve. UPDATE
    # explicite (et non attributs Python) : voir la note de login sur les copies perimees en memoire.
    await db.execute(
        update(Utilisateur)
        .where(Utilisateur.id == utilisateur.id)
        .values(
            mot_de_passe_hash=hash_password(payload.mot_de_passe),
            tentatives_echouees=0,
            verrouille_jusqua=None,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    sujet = str(utilisateur.id)
    return TokenResponse(
        access_token=create_access_token(sujet),
        refresh_token=create_refresh_token(sujet),
    )
