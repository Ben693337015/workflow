"""
Signature graphique de l'approbateur final d'un achat (Direction generale, role Signataire, section 8 du CDC technique).

On teste la chaine entiere, pas seulement le code retour : l'image tracee est validee, stockee A L'IDENTIQUE, puis
VISIBLE dans le bon de commande PDF (extraction reelle des images du PDF), et une signature absente, illisible ou vide
est refusee SANS bruler le jeton de decision ni avancer le circuit.
"""
import base64
import io
import subprocess

from PIL import Image
from sqlalchemy import select

from app.models.demande import Demande
from app.models.enums import RoleUtilisateur
from app.models.etape_workflow import EtapeWorkflow
from app.services import stockage_fichiers
from tests.integration.test_emails_trois_circuits import (  # noqa: F401  (fixtures et utilitaires partages)
    _a, _achat, _budget, _decider, _h, _jeton, _liens, _u, boite,
)
from tests.signature_factory import SIGNATURE_AUTRE_PNG, SIGNATURE_PNG, b64, png_signature


async def _jusqu_a_la_signature(client, db_session, boite, avec_budget=True):
    """Achat soumis, avis juridique favorable : la Direction generale doit signer. Renvoie (emp, dg, jur, did, jeton_signer)."""
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, nom="Marie Directrice", service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Awa Diop")
    if avec_budget:
        await _budget(db_session)
    achat = await _achat(client, emp)
    assert (await _decider(client, _jeton(boite[0], "Approuver"), jur)).status_code == 200
    mail_dg = boite[1]
    assert {l for _j, l in _liens(mail_dg)} == {"Signer", "Refuser"}
    return emp, dg, jur, achat["id"], _jeton(mail_dg, "Signer")


async def _etape_dg(db, did):
    requete = (select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid_(did), EtapeWorkflow.niveau == 2)
               .execution_options(populate_existing=True))
    return (await db.execute(requete)).scalar_one()


def uuid_(valeur):
    import uuid
    return uuid.UUID(valeur)


async def _statut(db, did):
    requete = select(Demande).where(Demande.id == uuid_(did)).execution_options(populate_existing=True)
    return (await db.execute(requete)).scalar_one().statut_global.value


def _images_du_pdf(pdf: bytes, tmp_path):
    """[(largeur, hauteur, PIL.Image)] de toutes les images embarquees dans le PDF (pdfimages)."""
    fichier = tmp_path / "bc.pdf"
    fichier.write_bytes(pdf)
    dossier = tmp_path / "img"
    dossier.mkdir(exist_ok=True)
    subprocess.run(["pdfimages", "-png", str(fichier), str(dossier / "i")], check=True)
    images = []
    for chemin in sorted(dossier.glob("i-*.png")):
        image = Image.open(chemin)
        image.load()
        images.append((image.width, image.height, image))
    return images


def _texte_pdf(pdf: bytes, tmp_path) -> str:
    fichier = tmp_path / "bc-texte.pdf"
    fichier.write_bytes(pdf)
    sortie = subprocess.run(["pdftotext", "-layout", str(fichier), "-"], capture_output=True, text=True, check=True)
    return " ".join(sortie.stdout.split())


def _a_du_trait(image: Image.Image) -> bool:
    """Vrai si l'image n'est pas uniforme (un trait existe)."""
    extrema = image.convert("L").getextrema()
    return extrema[0] != extrema[1]


# ============================================================================ la signature tracee arrive dans le bon de commande
async def test_la_signature_tracee_est_stockee_a_l_identique_et_visible_dans_le_bon_de_commande(
    client, db_session, boite, tmp_path
):
    emp, dg, _jur, did, jeton = await _jusqu_a_la_signature(client, db_session, boite)

    r = await _decider(client, jeton, dg, {"signature_image_base64": SIGNATURE_PNG})
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"

    # 1. stockee octet pour octet, rattachee a l'etape du signataire
    etape = await _etape_dg(db_session, did)
    assert etape.signature_cle_stockage and etape.approbateur_attendu_id == dg.id
    assert stockage_fichiers.lire_fichier(etape.signature_cle_stockage) == base64.b64decode(SIGNATURE_PNG)

    # 2. le bon de commande contient une image 360 x 140 avec un vrai trait
    r = await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(emp))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    import os
    if os.environ.get("BC_DUMP"):                       # revue visuelle : BC_DUMP=<fichier.pdf>
        open(os.environ["BC_DUMP"], "wb").write(r.content)
    images = _images_du_pdf(r.content, tmp_path)
    signatures = [i for (w, h, i) in images if (w, h) == (360, 140)]
    assert signatures, f"aucune image 360x140 dans le PDF : {[(w, h) for w, h, _ in images]}"
    assert any(_a_du_trait(i) for i in signatures)

    # 3. le texte du bon nomme le signataire et la date, et ne signale aucun manque
    texte = _texte_pdf(r.content, tmp_path)
    assert "Marie Directrice" in texte and "Direction générale — Signé électroniquement le" in texte
    assert "introuvable" not in texte and "date inconnue" not in texte
    # le demandeur est prevenu que le bon signe l'attend
    assert "bon de commande signé" in _a(boite, emp.email)[-1]["html"]


async def test_deux_signatures_differentes_donnent_deux_bons_differents(client, db_session, boite, tmp_path):
    """Garde-fou contre une image « figee » : le trace de CHAQUE signataire doit se retrouver dans SON bon."""
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session)
    empreintes = []
    for signature in (SIGNATURE_PNG, SIGNATURE_AUTRE_PNG):
        boite.clear()
        did = (await _achat(client, emp))["id"]
        assert (await _decider(client, _jeton(boite[0], "Approuver"), jur)).status_code == 200
        assert (await _decider(client, _jeton(boite[1], "Signer"), dg, {"signature_image_base64": signature})).status_code == 200
        pdf = (await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(emp))).content
        images = _images_du_pdf(pdf, tmp_path)
        empreintes.append(sorted(i.tobytes() for (w, h, i) in images if (w, h) == (360, 140)))
        for fichier in (tmp_path / "img").glob("*"):
            fichier.unlink()
    assert empreintes[0] and empreintes[1] and empreintes[0] != empreintes[1]


# ============================================================================ signatures refusees : jeton et circuit intacts
async def test_une_signature_absente_illisible_ou_vide_est_refusee_sans_bruler_le_jeton(
    client, db_session, boite, tmp_path
):
    emp, dg, _jur, did, jeton = await _jusqu_a_la_signature(client, db_session, boite)

    png = png_signature()
    cas = {
        "absente": ({}, "signature est obligatoire"),
        "base64 invalide": ({"signature_image_base64": "pas du base64 !!!"}, "invalide"),
        "chaine vide": ({"signature_image_base64": ""}, "obligatoire"),
        "texte quelconque": ({"signature_image_base64": b64(b"Ceci n'est pas une image")}, "illisible"),
        "PNG tronque (en-tete seul)": ({"signature_image_base64": "iVBORw0KGgo="}, "illisible"),
        "PNG coupe en deux": ({"signature_image_base64": b64(png[: len(png) // 2])}, "illisible"),
        "JPEG deguise en signature": (
            {"signature_image_base64": b64(_octets(Image.new("RGB", (100, 40), (0, 0, 0)), "JPEG"))}, "PNG"),
        "PNG entierement transparent": (
            {"signature_image_base64": b64(_octets(Image.new("RGBA", (360, 140), (0, 0, 0, 0)), "PNG"))}, "vide"),
        "PNG entierement blanc": (
            {"signature_image_base64": b64(_octets(Image.new("RGB", (360, 140), (255, 255, 255)), "PNG"))}, "vide"),
        "image gigantesque": (
            {"signature_image_base64": b64(_octets(Image.new("RGBA", (5000, 10), (0, 0, 0, 255)), "PNG"))}, "Dimensions"),
    }
    for nom, (corps, fragment) in cas.items():
        r = await _decider(client, jeton, dg, corps)
        assert r.status_code == 422, f"{nom} : {r.status_code} {r.text}"
        assert fragment.lower() in r.json()["detail"].lower(), f"{nom} : {r.json()['detail']}"
        # rien n'a avance : etape en attente, aucune signature stockee, demande toujours en cours
        etape = await _etape_dg(db_session, did)
        assert etape.statut.value == "en_attente" and etape.signature_cle_stockage is None, nom
        assert await _statut(db_session, did) == "en_cours", nom

    # le MEME lien fonctionne ensuite avec une vraie signature
    r = await _decider(client, jeton, dg, {"signature_image_base64": SIGNATURE_PNG})
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"


async def test_une_signature_trop_lourde_est_refusee(client, db_session, boite):
    import os

    emp, dg, _jur, did, jeton = await _jusqu_a_la_signature(client, db_session, boite)
    bruit = Image.frombytes("RGBA", (800, 800), os.urandom(800 * 800 * 4))          # PNG de ~2,5 Mo
    r = await _decider(client, jeton, dg, {"signature_image_base64": b64(_octets(bruit, "PNG"))})
    assert r.status_code == 422 and "volumineuse" in r.json()["detail"]
    assert (await _etape_dg(db_session, did)).signature_cle_stockage is None


# ============================================================================ qui peut signer, et une seule fois
async def test_seule_la_direction_generale_attendue_peut_signer_et_une_seule_fois(client, db_session, boite):
    emp, dg, jur, did, jeton = await _jusqu_a_la_signature(client, db_session, boite)

    # le juriste (ou le demandeur) detient le lien mais n'est pas le signataire attendu
    for intrus in (jur, emp):
        r = await _decider(client, jeton, intrus, {"signature_image_base64": SIGNATURE_PNG})
        assert r.status_code == 403, r.text
    assert (await _etape_dg(db_session, did)).signature_cle_stockage is None
    # sans session : connexion exigee
    r = await client.post(f"/api/v1/decisions/{jeton}", json={"signature_image_base64": SIGNATURE_PNG})
    assert r.status_code == 401

    assert (await _decider(client, jeton, dg, {"signature_image_base64": SIGNATURE_PNG})).status_code == 200
    cle = (await _etape_dg(db_session, did)).signature_cle_stockage
    # seconde tentative avec une AUTRE signature : refusee, la premiere reste la seule
    r = await _decider(client, jeton, dg, {"signature_image_base64": SIGNATURE_AUTRE_PNG})
    assert r.status_code in (401, 409)
    assert (await _etape_dg(db_session, did)).signature_cle_stockage == cle
    assert stockage_fichiers.lire_fichier(cle) == base64.b64decode(SIGNATURE_PNG)


async def test_le_refus_de_la_direction_generale_ne_demande_pas_de_signature_et_ne_produit_pas_de_bon(
    client, db_session, boite
):
    emp, dg, _jur, did, _jeton_signer = await _jusqu_a_la_signature(client, db_session, boite)
    jeton_refus = _jeton(boite[1], "Refuser")
    r = await _decider(client, jeton_refus, dg, {"commentaire": "Budget reporté"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    assert (await _etape_dg(db_session, did)).signature_cle_stockage is None
    assert (await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(emp))).status_code == 409
    assert "refusée" in _a(boite, emp.email)[-1]["subject"]


async def test_un_achat_sans_signature_valide_n_a_jamais_de_bon_signe(client, db_session, boite):
    emp, dg, _jur, did, jeton = await _jusqu_a_la_signature(client, db_session, boite)
    assert (await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(emp))).status_code == 409
    await _decider(client, jeton, dg, {"signature_image_base64": "iVBORw0KGgo="})
    assert (await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(emp))).status_code == 409


def _octets(image: Image.Image, format_: str) -> bytes:
    sortie = io.BytesIO()
    (image.convert("RGB") if format_ == "JPEG" else image).save(sortie, format=format_)
    return sortie.getvalue()
