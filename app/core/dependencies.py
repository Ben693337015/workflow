"""
Dépendances FastAPI transverses (section 3.2 / 5 du CDC technique).

get_current_user centralise le contrôle d'accès sur chaque route protégée.
get_current_user_optional est dédiée à la page de décision publique
(section 9.1, option B) : elle ne lève jamais 401 elle-même, elle renvoie
None si aucune session valide n'est présente - à charge de l'appelant de
décider si une session est obligatoire dans son contexte.
exiger_roles est un contrôle d'accès par rôle (écart identifié : nécessaire
pour réserver la régularisation de congés aux managers/DRH).
"""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Utilisateur:
    """Decode le JWT, resout l'utilisateur en base, leve 401 si invalide."""
    try:
        payload = decode_token(token)
        # Ecart identifie et corrige (revue du 15/09) : le type du jeton
        # n'etait jamais verifie ici - un jeton de rafraichissement (duree
        # de vie longue, section 5) pouvait donc servir directement de jeton
        # d'acces sur n'importe quelle route protegee, videant de son sens
        # la duree de vie courte voulue pour l'acces (cf. /auth/refresh, qui
        # applique deja symetriquement ce controle sur le jeton inverse).
        if payload.get("type") != "access":
            raise ValueError("Ce jeton n'est pas un jeton d'accès.")
        utilisateur_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    utilisateur = await db.get(Utilisateur, utilisateur_id)
    if utilisateur is None or not utilisateur.actif:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable ou inactif.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return utilisateur


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Utilisateur | None:
    """Variante non bloquante de get_current_user, pour la page de decision publique."""
    if token is None:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


def exiger_roles(*roles: RoleUtilisateur):
    """
    Fabrique une dépendance qui n'autorise l'accès qu'aux rôles listés.

    Exemple : Depends(exiger_roles(RoleUtilisateur.MANAGER, RoleUtilisateur.DRH))
    """

    async def verificateur(current_user: Utilisateur = Depends(get_current_user)) -> Utilisateur:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rôle insuffisant pour effectuer cette action.",
            )
        return current_user

    return verificateur
