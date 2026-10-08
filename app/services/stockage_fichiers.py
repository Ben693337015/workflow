"""
Stockage des pièces jointes (section 3.3 du CDC technique).

Point d'abstraction unique, même principe que app/services/email_service.py
pour l'envoi d'e-mails (section 14.2) : les appelants ne connaissent que
`enregistrer_fichier`/`lire_fichier`, jamais l'emplacement réel. NubiS3
(compatible S3, section 3.3) n'est pas raccordé à ce jour ("Point restant
à trancher", voir le README) — ce module écrit sur disque local en
attendant, mais le contrat (clé de stockage opaque en entrée/sortie,
octets bruts) ne changera pas le jour où NubiS3 sera branché : seul ce
fichier changera de forme interne.

Écart trouvé et corrigé (revue du 27/09) : le modèle PieceJointe
(app/models/piece_jointe.py) existe depuis la migration initiale mais
n'était utilisé nulle part dans le code - "Fichier du contrat", une des
quatre données clés à capturer pour les achats (CDC fonctionnel, section
3), n'avait donc aucun moyen d'être réellement déposé.
"""
import logging
import os
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlparse

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Deux implementations derriere le MEME contrat (cle opaque en entree/sortie, octets bruts) :
#  - S3 (NubieS3 / Backblaze B2, ou tout service compatible S3) si les 4 variables S3_ENDPOINT_URL, S3_BUCKET,
#    S3_ACCESS_KEY et S3_SECRET_KEY sont renseignees ;
#  - dossier local (STOCKAGE_FICHIERS_DOSSIER) sinon - developpement, tests, installation simple.
# La cle stockee en base (PieceJointe.cle_stockage) est identique dans les deux cas : on peut donc passer du disque
# a S3 sans toucher a la base (voir scripts/migrer_fichiers_vers_s3.py).


class StockageMalConfigure(RuntimeError):
    """Configuration S3 incomplete : mieux vaut refuser de demarrer que perdre des fichiers en silence sur le disque."""


def _champs_s3() -> dict[str, str]:
    return {
        "S3_ENDPOINT_URL": settings.s3_endpoint_url.strip(),
        "S3_BUCKET": settings.s3_bucket.strip(),
        "S3_ACCESS_KEY": settings.s3_access_key.strip(),
        "S3_SECRET_KEY": settings.s3_secret_key.strip(),
    }


def utilise_s3() -> bool:
    """True si S3 est entierement configure ; False si aucune variable S3 ; erreur si configuration partielle."""
    champs = _champs_s3()
    renseignes = [nom for nom, valeur in champs.items() if valeur]
    if not renseignes:
        return False
    manquants = [nom for nom, valeur in champs.items() if not valeur]
    if manquants:
        raise StockageMalConfigure(
            "Configuration S3 incomplete : variable(s) manquante(s) : " + ", ".join(manquants)
            + ". Renseignez les 4 variables S3_* ou videz-les toutes pour utiliser le dossier local."
        )
    return True


def description_stockage() -> str:
    """Texte pour le journal de demarrage (jamais de secret)."""
    if utilise_s3():
        return f"S3 (bucket {settings.s3_bucket}, endpoint {settings.s3_endpoint_url}, prefixe '{_prefixe()}')"
    return f"dossier local {settings.stockage_fichiers_dossier}"


def _prefixe() -> str:
    p = settings.s3_prefix.strip().lstrip("/")
    return p if not p or p.endswith("/") else p + "/"


def _region() -> str:
    if settings.s3_region.strip():
        return settings.s3_region.strip()
    # Backblaze / la plupart des fournisseurs : s3.<region>.<domaine> - sinon valeur neutre acceptee par la signature v4.
    hote = urlparse(settings.s3_endpoint_url).hostname or ""
    morceaux = hote.split(".")
    return morceaux[1] if len(morceaux) > 2 and morceaux[0] == "s3" else "us-east-1"


@lru_cache(maxsize=4)
def _client_s3(endpoint: str, access: str, secret: str, region: str):
    import boto3
    from botocore.config import Config

    # request/response_checksum_* = when_required : les versions recentes de boto3 ajoutent par defaut des
    # sommes de controle que Backblaze B2 et plusieurs services S3 compatibles ne gerent pas (erreurs a l'envoi).
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        retries={"max_attempts": 5, "mode": "standard"},
        connect_timeout=10,
        read_timeout=60,
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=access, aws_secret_access_key=secret,
        region_name=region, config=config,
    )


def _s3():
    return _client_s3(
        settings.s3_endpoint_url.strip(), settings.s3_access_key.strip(), settings.s3_secret_key.strip(), _region()
    )


def _cle_objet(cle_stockage: str) -> str:
    return _prefixe() + cle_stockage


def _dossier_stockage() -> Path:
    dossier = Path(settings.stockage_fichiers_dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def enregistrer_fichier(contenu: bytes, nom_original: str) -> str:
    """
    Ecrit le contenu (S3 ou disque) et retourne une cle de stockage opaque
    (a persister dans PieceJointe.cle_stockage) - jamais le nom de fichier
    d'origine directement, pour eviter toute collision ou traversee de
    chemin (`../../etc/passwd` etc.) si nom_original n'est pas fiable.
    Appel bloquant : depuis une route asynchrone, l'appeler via asyncio.to_thread.
    """
    extension = Path(nom_original).suffix
    cle = f"{uuid.uuid4().hex}{extension}"
    if utilise_s3():
        _s3().put_object(Bucket=settings.s3_bucket, Key=_cle_objet(cle), Body=contenu)
    else:
        (_dossier_stockage() / cle).write_bytes(contenu)
    return cle


def lire_fichier(cle_stockage: str) -> bytes:
    """Relit le contenu associe a une cle renvoyee par enregistrer_fichier. FileNotFoundError si absent (S3 comme disque)."""
    if utilise_s3():
        from botocore.exceptions import ClientError

        try:
            return _s3().get_object(Bucket=settings.s3_bucket, Key=_cle_objet(cle_stockage))["Body"].read()
        except ClientError as erreur:
            if erreur.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(cle_stockage) from erreur
            raise
    return (_dossier_stockage() / cle_stockage).read_bytes()


def supprimer_fichier(cle_stockage: str) -> None:
    """Supprime le fichier (sans erreur s'il n'existe pas) - jamais appele pour l'instant, fourni pour completude."""
    if utilise_s3():
        _s3().delete_object(Bucket=settings.s3_bucket, Key=_cle_objet(cle_stockage))
        return
    chemin = _dossier_stockage() / cle_stockage
    if chemin.exists():
        os.remove(chemin)


def verifier_acces_s3() -> str:
    """
    Controle de bout en bout du bucket (ecriture, relecture, suppression d'un objet de test) : a lancer apres avoir
    renseigne les cles (`python -m scripts.verifier_stockage`). Retourne un message ; leve en cas d'echec.
    """
    if not utilise_s3():
        raise StockageMalConfigure("S3 non configure : rien a verifier (stockage sur dossier local).")
    cle = enregistrer_fichier(b"verification-stockage", "test.txt")
    try:
        if lire_fichier(cle) != b"verification-stockage":
            raise RuntimeError("Le contenu relu ne correspond pas au contenu envoye.")
    finally:
        supprimer_fichier(cle)
    return f"OK : ecriture, lecture et suppression reussies sur {description_stockage()}"


# --- Validation partagee des fichiers deposes (contrat des achats, pieces de la discussion) ---

TYPES_ACCEPTES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
}
# Taille maximale d'un fichier depose (contrat des achats, justificatifs, pieces de la discussion).
# Passee de 10 a 30 Mo (05/10/2026), puis a 40 Mo (07/10/2026). Source unique : le message d'erreur en est derive, et l'interface
# affiche la meme valeur (frontend/src/lib/fichiers.ts - a garder identique).
# Si un reverse proxy se trouve devant l'application (nginx : client_max_body_size), il doit accepter AU MOINS
# cette taille plus l'enveloppe multipart, sinon il refuse le fichier avant qu'il n'atteigne l'application.
TAILLE_MAX_MO = 40
TAILLE_MAX_OCTETS = TAILLE_MAX_MO * 1024 * 1024


def verifier_fichier(content_type: str | None, contenu: bytes) -> str | None:
    """Retourne un message d'erreur (a renvoyer en 422) ou None si le fichier est acceptable."""
    if content_type not in TYPES_ACCEPTES:
        return "Format de fichier non accepté (PDF, Word, PNG ou JPEG uniquement)."
    if not contenu:
        return "Le fichier est vide."
    if len(contenu) > TAILLE_MAX_OCTETS:
        return f"Le fichier dépasse la taille maximale autorisée ({TAILLE_MAX_MO} Mo)."
    return None


async def lire_depot(fichier) -> bytes:
    """
    Lit un fichier depose (UploadFile) en s'arretant a la taille maximale + 1 octet : un fichier plus gros est
    ainsi detecte par `verifier_fichier` sans jamais etre charge en entier en memoire.
    """
    return await fichier.read(TAILLE_MAX_OCTETS + 1)


def en_tete_telechargement(nom_original: str) -> str:
    """
    Valeur d'un en-tete Content-Disposition pour un nom de fichier fourni par
    l'utilisateur. Un nom brut entre guillemets pouvait contenir un guillemet ou
    un saut de ligne et corrompre l'en-tete : on utilise la forme RFC 5987
    (`filename*=UTF-8''...`, pourcentage-encodee), avec un repli ASCII neutre.
    """
    return f"attachment; filename=\"fichier\"; filename*=UTF-8''{quote(nom_original, safe='')}"
