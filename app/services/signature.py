"""
Controle de l'image de signature graphique (role Signataire, section 8 du CDC technique).

Avant (07/10) le serveur acceptait n'importe quels octets decodables en base64 : un PNG tronque, un fichier
quelconque ou une image entierement vide. Le bon de commande affichait alors « Signe electroniquement » sans aucun
trace visible (l'image illisible etait ignoree en silence par le moteur PDF). Une signature n'est acceptee que si :
- c'est un VRAI PNG, complet et lisible ;
- ses dimensions restent raisonnables (le pad de l'interface produit 360 x 140 px) et son poids aussi ;
- elle contient au moins un trait visible (pixel non transparent et non blanc).
"""
import io

from PIL import Image, ImageChops, UnidentifiedImageError

TAILLE_MAX_OCTETS = 1_000_000          # un trace a la souris fait quelques Ko ; 1 Mo est deja tres large
COTE_MAX_PX = 4000


class SignatureInvalide(ValueError):
    """Message destine a l'utilisateur (422)."""


_FIN_PNG = b"IEND\xaeB`\x82"       # chunk final d'un PNG complet (type + CRC fixe)


def valider_signature_png(octets: bytes) -> None:
    if len(octets) > TAILLE_MAX_OCTETS:
        raise SignatureInvalide("Image de signature trop volumineuse (1 Mo maximum).")
    # WeasyPrint active GLOBALEMENT `ImageFile.LOAD_TRUNCATED_IMAGES` : Pillow accepterait alors un PNG coupe.
    # On exige donc explicitement le chunk de fin, independamment de ce reglage.
    if not octets.endswith(_FIN_PNG):
        raise SignatureInvalide("Image de signature illisible (PNG valide attendu).")
    try:
        with Image.open(io.BytesIO(octets)) as image:
            if image.format != "PNG":
                raise SignatureInvalide("La signature doit être une image PNG.")
            largeur, hauteur = image.size
            if not (0 < largeur <= COTE_MAX_PX and 0 < hauteur <= COTE_MAX_PX):
                raise SignatureInvalide("Dimensions de l'image de signature invalides.")
            image.load()                       # leve si le fichier est tronque / corrompu
            rgba = image.convert("RGBA")
    except SignatureInvalide:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise SignatureInvalide("Image de signature illisible (PNG valide attendu).") from exc

    rouge, vert, bleu, alpha = rgba.split()
    plus_sombre = ImageChops.darker(ImageChops.darker(rouge, vert), bleu)
    encre = plus_sombre.point(lambda v: 255 if v < 250 else 0)       # pas blanc
    visible = alpha.point(lambda v: 255 if v > 0 else 0)             # pas transparent
    if ImageChops.multiply(encre, visible).getbbox() is None:
        raise SignatureInvalide("La signature est vide : tracez-la avant de valider.")
