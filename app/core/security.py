"""
Primitives de sécurité : hachage des mots de passe et jetons JWT (section 5).

Implémentation minimale nécessaire pour que la vérification de session de la
route de décision (option B, section 9.1) soit réellement testable - le
flux complet de gestion de compte (inscription, réinitialisation de mot de
passe) reste hors périmètre pour l'instant.
"""
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hache un mot de passe en clair avec bcrypt (sel généré automatiquement)."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie un mot de passe en clair contre son hachage."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
    """Génère un JWT d'accès à durée de vie courte (section 5)."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "type": "access", "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(subject: str) -> str:
    """Génère un JWT de rafraîchissement à durée de vie longue (section 5)."""
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    return jwt.encode(
        {"sub": subject, "type": "refresh", "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict:
    """Décode et valide un JWT (signature + expiration). Lève ValueError sinon."""
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Jeton d'accès invalide ou expiré.") from exc
