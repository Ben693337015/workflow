"""Tests unitaires - validation de fichiers et en-tete de telechargement sur."""
from app.services import stockage_fichiers


def test_en_tete_de_telechargement_neutralise_guillemets_points_virgules_et_sauts_de_ligne():
    entete = stockage_fichiers.en_tete_telechargement('a"b;c\r\nX-Evil: 1.pdf')

    assert "\r" not in entete and "\n" not in entete
    assert entete.count('"') == 2  # uniquement les guillemets du repli fixe filename="fichier"
    assert "%0D%0A" in entete
    assert "%22" in entete and "%3B" in entete


def test_en_tete_de_telechargement_conserve_les_accents():
    assert "filename*=UTF-8''justificatif%20m%C3%A9dical.pdf" in stockage_fichiers.en_tete_telechargement(
        "justificatif médical.pdf"
    )


def test_verifier_fichier_accepte_un_pdf_et_refuse_type_vide_et_trop_gros():
    assert stockage_fichiers.verifier_fichier("application/pdf", b"%PDF") is None
    assert "Format" in stockage_fichiers.verifier_fichier("application/x-msdownload", b"x")
    assert "vide" in stockage_fichiers.verifier_fichier("application/pdf", b"")
    trop_gros = b"0" * (stockage_fichiers.TAILLE_MAX_OCTETS + 1)
    assert "40 Mo" in stockage_fichiers.verifier_fichier("application/pdf", trop_gros)
    assert stockage_fichiers.verifier_fichier("application/pdf", trop_gros[:-1]) is None  # borne incluse


def test_la_taille_maximale_est_de_30_mo():
    """Valeurs litterales : la limite est passee de 10 a 30 Mo (05/10/2026) puis 40 Mo (07/10/2026), un changement accidentel doit se voir."""
    mo = 1024 * 1024
    assert stockage_fichiers.TAILLE_MAX_MO == 40
    assert stockage_fichiers.TAILLE_MAX_OCTETS == 40 * mo
    for taille in (1, 10 * mo, 10 * mo + 1, 29 * mo, 30 * mo, 39 * mo, 40 * mo):  # 10 Mo + 1 etait refuse avant
        assert stockage_fichiers.verifier_fichier("application/pdf", b"0" * taille) is None, taille
    assert stockage_fichiers.verifier_fichier("application/pdf", b"0" * (40 * mo + 1)) is not None


async def test_la_lecture_d_un_depot_s_arrete_a_la_taille_maximale_plus_un_octet():
    """Un fichier enorme n'est pas charge en entier en memoire : on lit au plus 40 Mo + 1 octet, assez pour le refuser."""
    class Faux:
        demande = None

        async def read(self, n=-1):
            Faux.demande = n
            return b"0" * (n if n > 0 else 10**9)

    contenu = await stockage_fichiers.lire_depot(Faux())

    assert Faux.demande == 40 * 1024 * 1024 + 1
    assert len(contenu) == 40 * 1024 * 1024 + 1
    assert stockage_fichiers.verifier_fichier("application/pdf", contenu) is not None
