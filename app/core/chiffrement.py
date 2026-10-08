"""
Chiffrement au repos des secrets applicatifs (correction R22, CDC technique 4.2.10 : le secret de
signature d'un abonnement webhook doit etre « stocke chiffre »).

Avant : `abonnements_webhook.secret_hmac` etait stocke en clair. Une fuite de la base (sauvegarde,
dump, acces en lecture) permettait de forger des notifications signees vers les systemes tiers.

Choix : chiffrement authentifie Fernet (AES-128-CBC + HMAC-SHA256, bibliotheque `cryptography`,
deja presente via python-jose). Une valeur chiffree porte le prefixe `fernet:` : cela permet de
distinguer sans ambiguite une valeur chiffree d'un ancien secret en clair, qui reste lisible tant
qu'il n'a pas ete migre.

Cle : `WEBHOOK_ENCRYPTION_KEY` (cle Fernet, generee par `python -c "from cryptography.fernet import
Fernet; print(Fernet.generate_key().decode())"`). A defaut, une cle est derivee de SECRET_KEY par
SHA-256. Attention : changer cette cle rend les secrets deja chiffres illisibles ; il faut alors les
regenerer. La cle doit etre distincte de la base de donnees (variable d'environnement).
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

PREFIXE = "fernet:"


def _fernet() -> Fernet:
    reglages = get_settings()
    if reglages.webhook_encryption_key:
        return Fernet(reglages.webhook_encryption_key.encode())
    derivee = hashlib.sha256(("webhook-secret-v1:" + reglages.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derivee))


def est_chiffre(valeur: str) -> bool:
    return valeur.startswith(PREFIXE)


def chiffrer_secret(clair: str) -> str:
    """Chiffre un secret. Idempotent : une valeur deja chiffree est renvoyee telle quelle."""
    if est_chiffre(clair):
        return clair
    return PREFIXE + _fernet().encrypt(clair.encode()).decode()


def dechiffrer_secret(stocke: str) -> str:
    """
    Retourne le secret en clair. Une valeur sans prefixe est un ancien secret non migre : elle est
    renvoyee telle quelle (compatibilite). Une valeur chiffree illisible (cle changee, donnee
    alteree) leve `ValueError`.
    """
    if not est_chiffre(stocke):
        return stocke
    try:
        return _fernet().decrypt(stocke[len(PREFIXE):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Secret webhook illisible : cle de chiffrement modifiee ou donnee alteree.") from exc
