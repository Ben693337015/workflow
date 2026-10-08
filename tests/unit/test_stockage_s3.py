"""Stockage des pieces jointes : implementation S3 (faux S3 `moto`) et repli sur le dossier local."""
import boto3
import pytest
from moto.server import ThreadedMotoServer

from app.services import stockage_fichiers as st

BUCKET = "nubie-test"
REGION = "eu-central-003"


@pytest.fixture(scope="module")
def serveur_s3():
    # Serveur S3 simule reel (HTTP local) : le client de production est donc exerce tel quel, avec un endpoint
    # personnalise comme celui de NubieS3 - un simple mock en memoire n'intercepte pas les endpoints non AWS.
    serveur = ThreadedMotoServer(port=0, verbose=False)
    serveur.start()
    hote, port = serveur.get_host_and_port()
    yield f"http://{hote}:{port}"
    serveur.stop()


@pytest.fixture
def s3(serveur_s3, monkeypatch):
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    client = boto3.client("s3", region_name=REGION, endpoint_url=serveur_s3,
                          aws_access_key_id="k", aws_secret_access_key="s")
    client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    for nom, valeur in {"s3_endpoint_url": serveur_s3, "s3_bucket": BUCKET, "s3_access_key": "k",
                        "s3_secret_key": "s", "s3_region": REGION, "s3_prefix": "workflows/"}.items():
        monkeypatch.setattr(st.settings, nom, valeur)
    st._client_s3.cache_clear()
    yield client
    for objet in client.list_objects_v2(Bucket=BUCKET).get("Contents", []):
        client.delete_object(Bucket=BUCKET, Key=objet["Key"])
    client.delete_bucket(Bucket=BUCKET)
    st._client_s3.cache_clear()


def test_aller_retour_s3_avec_prefixe_et_cle_opaque(s3):
    cle = st.enregistrer_fichier(b"%PDF-contenu", "../../etc/Contrat final.pdf")
    assert cle.endswith(".pdf") and "/" not in cle and " " not in cle      # cle opaque, jamais le nom d'origine
    assert st.lire_fichier(cle) == b"%PDF-contenu"
    objets = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert objets == [f"workflows/{cle}"]                                  # prefixe cote bucket, pas dans la cle en base


def test_fichier_absent_leve_file_not_found_comme_sur_disque(s3):
    with pytest.raises(FileNotFoundError):
        st.lire_fichier("inexistant.pdf")


def test_suppression_et_suppression_d_un_absent(s3):
    cle = st.enregistrer_fichier(b"x", "a.png")
    st.supprimer_fichier(cle)
    with pytest.raises(FileNotFoundError):
        st.lire_fichier(cle)
    st.supprimer_fichier(cle)  # idempotent


def test_gros_fichier_40_mo(s3):
    contenu = b"\x01" * (40 * 1024 * 1024)
    cle = st.enregistrer_fichier(contenu, "gros.pdf")
    assert st.lire_fichier(cle) == contenu


def test_region_deduite_de_l_endpoint_et_surchargeable(monkeypatch):
    monkeypatch.setattr(st.settings, "s3_region", "")
    monkeypatch.setattr(st.settings, "s3_endpoint_url", "https://s3.eu-central-003.backblazeb2.com")
    assert st._region() == "eu-central-003"
    monkeypatch.setattr(st.settings, "s3_region", "us-west-004")
    assert st._region() == "us-west-004"
    monkeypatch.setattr(st.settings, "s3_region", "")
    monkeypatch.setattr(st.settings, "s3_endpoint_url", "http://localhost:9000")
    assert st._region() == "us-east-1"


def test_verification_bout_en_bout(s3):
    assert st.verifier_acces_s3().startswith("OK")
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)              # l'objet de test est supprime


def test_mauvais_bucket_donne_une_erreur_claire_pas_un_disque_silencieux(s3, monkeypatch):
    monkeypatch.setattr(st.settings, "s3_bucket", "n-existe-pas")
    with pytest.raises(Exception) as erreur:
        st.enregistrer_fichier(b"x", "a.pdf")
    assert "NoSuchBucket" in str(erreur.value)


def test_configuration_partielle_refusee(monkeypatch):
    monkeypatch.setattr(st.settings, "s3_endpoint_url", "https://s3.eu-central-003.backblazeb2.com")
    monkeypatch.setattr(st.settings, "s3_bucket", BUCKET)
    monkeypatch.setattr(st.settings, "s3_access_key", "")
    monkeypatch.setattr(st.settings, "s3_secret_key", "")
    with pytest.raises(st.StockageMalConfigure) as erreur:
        st.enregistrer_fichier(b"x", "a.pdf")
    assert "S3_ACCESS_KEY" in str(erreur.value) and "S3_SECRET_KEY" in str(erreur.value)
    with pytest.raises(st.StockageMalConfigure):
        st.description_stockage()


def test_sans_variables_s3_repli_sur_le_disque(monkeypatch, tmp_path):
    for nom in ("s3_endpoint_url", "s3_bucket", "s3_access_key", "s3_secret_key"):
        monkeypatch.setattr(st.settings, nom, "")
    monkeypatch.setattr(st.settings, "stockage_fichiers_dossier", str(tmp_path / "pj"))
    assert st.utilise_s3() is False
    cle = st.enregistrer_fichier(b"disque", "a.pdf")
    assert (tmp_path / "pj" / cle).read_bytes() == b"disque" and st.lire_fichier(cle) == b"disque"
    assert "dossier local" in st.description_stockage()
    with pytest.raises(st.StockageMalConfigure):
        st.verifier_acces_s3()


def test_description_ne_contient_aucun_secret(s3, monkeypatch):
    monkeypatch.setattr(st.settings, "s3_secret_key", "SECRET-ULTRA")
    monkeypatch.setattr(st.settings, "s3_access_key", "ACCES-ID")
    d = st.description_stockage()
    assert "SECRET-ULTRA" not in d and "ACCES-ID" not in d and BUCKET in d


def test_script_migration_copie_sans_toucher_au_local_et_est_relancable(s3, monkeypatch, tmp_path, capsys):
    from scripts import migrer_fichiers_vers_s3 as mig
    local = tmp_path / "pj"
    local.mkdir()
    (local / "aaa.pdf").write_bytes(b"un")
    (local / "bbb.png").write_bytes(b"deux!")
    monkeypatch.setattr(st.settings, "stockage_fichiers_dossier", str(local))

    assert mig.migrer(dry_run=True) == (2, 0, 0)
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)           # dry-run : rien n'est envoye
    assert mig.migrer(dry_run=False) == (2, 0, 0)
    assert st.lire_fichier("aaa.pdf") == b"un" and st.lire_fichier("bbb.png") == b"deux!"   # memes cles qu'en local
    assert sorted(p.name for p in local.iterdir()) == ["aaa.pdf", "bbb.png"]                # local intact
    assert mig.migrer(dry_run=False) == (0, 2, 0)                                           # relance : rien a refaire


def test_script_migration_refuse_sans_s3(monkeypatch):
    from scripts import migrer_fichiers_vers_s3 as mig
    for nom in ("s3_endpoint_url", "s3_bucket", "s3_access_key", "s3_secret_key"):
        monkeypatch.setattr(st.settings, nom, "")
    with pytest.raises(st.StockageMalConfigure):
        mig.migrer(dry_run=False)


def test_script_verification_codes_de_sortie(s3, monkeypatch):
    from scripts import verifier_stockage
    assert verifier_stockage.main() == 0
    monkeypatch.setattr(st.settings, "s3_bucket", "inconnu")
    assert verifier_stockage.main() == 1
