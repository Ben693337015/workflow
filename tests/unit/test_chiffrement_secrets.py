"""Correction R22 : le secret HMAC des abonnements webhook n'est plus stocke en clair."""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from app.core import chiffrement
from app.core.config import get_settings
from app.models.abonnement_webhook import AbonnementWebhook
from app.models.enums import EvenementWebhook, RoleUtilisateur, TypeProcessus
from app.services import webhooks


def test_aller_retour():
    assert chiffrement.dechiffrer_secret(chiffrement.chiffrer_secret("mon-secret")) == "mon-secret"


def test_la_valeur_stockee_ne_contient_pas_le_secret_et_porte_le_prefixe():
    stocke = chiffrement.chiffrer_secret("mon-secret-tres-visible")
    assert stocke.startswith("fernet:")
    assert "mon-secret-tres-visible" not in stocke


def test_deux_chiffrements_du_meme_secret_different():
    """Aleatoire par chiffrement : on ne peut pas reperer deux abonnements qui partagent un secret."""
    assert chiffrement.chiffrer_secret("abc") != chiffrement.chiffrer_secret("abc")


def test_chiffrer_est_idempotent():
    une_fois = chiffrement.chiffrer_secret("abc")
    assert chiffrement.chiffrer_secret(une_fois) == une_fois


def test_un_ancien_secret_en_clair_reste_lisible():
    assert chiffrement.dechiffrer_secret("ancien-secret-non-migre") == "ancien-secret-non-migre"


def test_une_valeur_alteree_est_refusee():
    stocke = chiffrement.chiffrer_secret("abc")
    altere = stocke[:-3] + ("AAA" if not stocke.endswith("AAA") else "BBB")
    with pytest.raises(ValueError):
        chiffrement.dechiffrer_secret(altere)


def test_un_secret_long_tient_dans_la_colonne():
    """La colonne fait 512 caracteres : un secret de 250 caracteres, une fois chiffre, doit y tenir."""
    assert len(chiffrement.chiffrer_secret("x" * 250)) <= 512


def test_changer_la_cle_rend_les_secrets_illisibles(monkeypatch):
    stocke = chiffrement.chiffrer_secret("abc")
    monkeypatch.setattr(get_settings(), "webhook_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        chiffrement.dechiffrer_secret(stocke)


def test_la_cle_dediee_est_utilisee_quand_elle_est_definie(monkeypatch):
    cle = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "webhook_encryption_key", cle)
    stocke = chiffrement.chiffrer_secret("abc")
    assert Fernet(cle.encode()).decrypt(stocke[len("fernet:"):].encode()) == b"abc"


async def test_creer_abonnement_stocke_chiffre_en_base(db_session):
    abonnement = await webhooks.creer_abonnement(
        db_session, "https://erp.example.com/hook", "secret-en-clair", TypeProcessus.CONGES, ["demande_soumise"]
    )
    await db_session.commit()

    brut = (await db_session.execute(text("SELECT secret_hmac FROM abonnements_webhook"))).scalar_one()
    assert "secret-en-clair" not in brut
    assert brut.startswith("fernet:")
    assert chiffrement.dechiffrer_secret(brut) == "secret-en-clair"
    assert abonnement.secret_hmac == brut


async def _client_http_factice(monkeypatch):
    envoi = AsyncMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=MagicMock(post=envoi))
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.webhooks.httpx.AsyncClient", lambda **_kw: client)
    return envoi


async def test_la_notification_est_signee_avec_le_secret_dechiffre(db_session, monkeypatch):
    await webhooks.creer_abonnement(
        db_session, "https://erp.example.com/hook", "secret-en-clair", TypeProcessus.CONGES, ["demande_soumise"]
    )
    await db_session.commit()
    envoi = await _client_http_factice(monkeypatch)

    await webhooks.notifier_evenement(db_session, "d-1", TypeProcessus.CONGES, EvenementWebhook.DEMANDE_SOUMISE)

    envoi.assert_awaited_once()
    corps = envoi.await_args.kwargs["content"]
    attendu = hmac.new(b"secret-en-clair", corps, hashlib.sha256).hexdigest()
    assert envoi.await_args.kwargs["headers"]["X-Signature-256"] == attendu
    assert json.loads(corps)["evenement"] == "demande_soumise"


async def test_un_abonnement_ancien_en_clair_continue_de_fonctionner(db_session, monkeypatch):
    db_session.add(
        AbonnementWebhook(
            url_destination="https://erp.example.com/hook", secret_hmac="ancien-secret",
            processus=TypeProcessus.CONGES, evenements=["demande_soumise"],
        )
    )
    await db_session.commit()
    envoi = await _client_http_factice(monkeypatch)

    await webhooks.notifier_evenement(db_session, "d-1", TypeProcessus.CONGES, EvenementWebhook.DEMANDE_SOUMISE)

    corps = envoi.await_args.kwargs["content"]
    assert envoi.await_args.kwargs["headers"]["X-Signature-256"] == hmac.new(
        b"ancien-secret", corps, hashlib.sha256
    ).hexdigest()


async def test_un_secret_illisible_est_ignore_sans_faire_echouer_les_autres(db_session, monkeypatch):
    db_session.add(
        AbonnementWebhook(
            url_destination="https://casse.example.com", secret_hmac="fernet:corrompu",
            processus=TypeProcessus.CONGES, evenements=["demande_soumise"],
        )
    )
    await webhooks.creer_abonnement(
        db_session, "https://ok.example.com", "bon-secret", TypeProcessus.CONGES, ["demande_soumise"]
    )
    await db_session.commit()
    envoi = await _client_http_factice(monkeypatch)

    await webhooks.notifier_evenement(db_session, "d-1", TypeProcessus.CONGES, EvenementWebhook.DEMANDE_SOUMISE)

    assert envoi.await_count == 1  # seul l'abonnement lisible est notifie, aucune exception
    assert envoi.await_args.args[0] == "https://ok.example.com"
