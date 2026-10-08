"""Circuit d'achat COMPLET avec le stockage S3 actif : contrat, signature et bon de commande transitent par le bucket."""
import base64
import os

from app.models.enums import RoleUtilisateur
from app.services import stockage_fichiers
from tests.integration.test_emails_trois_circuits import _h, boite  # noqa: F401
from tests.integration.test_signature_graphique import (  # noqa: F401
    _etape_dg, _images_du_pdf, _jusqu_a_la_signature, _decider,
)
from tests.signature_factory import SIGNATURE_PNG
from tests.unit.test_stockage_s3 import BUCKET, s3, serveur_s3  # noqa: F401


async def test_achat_contrat_signature_et_bon_de_commande_via_s3(client, db_session, boite, s3, tmp_path):
    emp, dg, _jur, did, jeton = await _jusqu_a_la_signature(client, db_session, boite)

    # le contrat depose a la soumission est dans le bucket (prefixe workflows/), pas sur le disque
    objets = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert len(objets) == 1 and objets[0].startswith("workflows/") and objets[0].endswith(".pdf")
    assert not os.path.exists(stockage_fichiers.settings.stockage_fichiers_dossier) or not os.listdir(
        stockage_fichiers.settings.stockage_fichiers_dossier)

    # telechargement du contrat par le demandeur : memes octets
    r = await client.get(f"/api/v1/achats/{did}/piece-jointe", headers=_h(emp))
    assert r.status_code == 200 and r.content == b"%PDF-1.4 x"

    # signature de la Direction generale -> stockee dans le bucket a l'identique
    r = await _decider(client, jeton, dg, {"signature_image_base64": SIGNATURE_PNG})
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    etape = await _etape_dg(db_session, did)
    assert stockage_fichiers.lire_fichier(etape.signature_cle_stockage) == base64.b64decode(SIGNATURE_PNG)
    cles = {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]}
    assert f"workflows/{etape.signature_cle_stockage}" in cles and len(cles) == 2

    # le bon de commande relit la signature depuis S3 et l'embarque dans le PDF
    r = await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(emp))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert any((w, h) == (360, 140) for w, h, _ in _images_du_pdf(r.content, tmp_path))


async def test_fichier_de_discussion_via_s3(client, db_session, boite, s3):
    emp, dg, jur, did, _ = await _jusqu_a_la_signature(client, db_session, boite)
    # l'avis juridique est deja donne : la DG est l'approbateur courant, elle suspend et le demandeur repond avec un fichier
    from tests.integration.test_emails_trois_circuits import _h as h
    r = await client.post(f"/api/v1/demandes/{did}/suspendre", headers=h(dg), json={"message": "Precisions ?"})
    assert r.status_code == 201, r.text
    r = await client.post(f"/api/v1/demandes/{did}/messages/avec-fichier", headers=h(emp),
                          data={"contenu": "Voir devis"},
                          files={"fichier": ("devis.pdf", b"%PDF-1.4 devis", "application/pdf")})
    assert r.status_code == 201, r.text
    assert len(s3.list_objects_v2(Bucket=BUCKET)["Contents"]) == 2   # contrat + devis
