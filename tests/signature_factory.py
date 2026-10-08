"""Signatures PNG realistes pour les tests : un trace de stylo comme celui du pad de l'interface (360 x 140 px)."""
import base64
import io

from PIL import Image, ImageDraw

ENCRE = (16, 20, 37, 255)            # #101425, la couleur du trait du pad


def png_signature(points=None, taille=(360, 140), fond=(0, 0, 0, 0)) -> bytes:
    """PNG transparent avec un trait de stylo (largeur 2, extremites arrondies) passant par `points`."""
    image = Image.new("RGBA", taille, fond)
    if points is None:
        points = [(20, 100), (60, 40), (100, 110), (150, 30), (200, 105), (260, 45), (330, 90)]
    dessin = ImageDraw.Draw(image)
    dessin.line(points, fill=ENCRE, width=2, joint="curve")
    sortie = io.BytesIO()
    image.save(sortie, format="PNG")
    return sortie.getvalue()


def b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode("ascii")


SIGNATURE_PNG = b64(png_signature())
SIGNATURE_AUTRE_PNG = b64(png_signature([(30, 30), (330, 120), (30, 120), (330, 30)]))
