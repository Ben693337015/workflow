"""
Tests unitaires du service d'envoi d'e-mails (app/services/email_service.py).

Écart identifié (revue du 16/09) : toute la suite existante mocke
`email_service.envoyer_email` au niveau des routeurs pour vérifier QUI est
notifié et avec QUEL contenu - mais rien ne vérifiait que `envoyer_email`
lui-même appelle correctement le SDK Resend (forme du payload, gestion des
erreurs). Ce fichier comble ce trou en mockant `resend.Emails.send`
directement, un niveau plus bas que le reste de la suite.
"""
import pytest

from app.services import email_service

pytestmark = pytest.mark.asyncio


async def test_envoyer_email_appelle_resend_avec_le_bon_payload(monkeypatch):
    appels = []
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda payload: appels.append(payload))

    await email_service.envoyer_email(
        destinataire="test@example.com", sujet="Sujet de test", corps_html="<p>Corps</p>"
    )

    assert len(appels) == 1
    payload = appels[0]
    # Forme exacte attendue par l'API Resend (section 14.2.1 du CDC).
    assert payload["to"] == ["test@example.com"]
    assert payload["subject"] == "Sujet de test"
    # Habillage commun : le contenu est conserve tel quel, le sujet devient le titre du message.
    assert payload["html"].startswith("<!doctype html>")
    assert "<p>Corps</p>" in payload["html"] and "<h1" in payload["html"] and "Sujet de test" in payload["html"]
    assert payload["from"] == email_service.settings.email_from


async def test_envoyer_email_ne_bloque_pas_la_boucle_devenements(monkeypatch):
    """
    Le SDK Resend est synchrone (§14.2.1) - un appel direct depuis une route
    async bloquerait la boucle d'événements pour tous les autres utilisateurs
    pendant l'appel réseau. Vérifie que l'appel passe bien par un thread
    séparé (asyncio.to_thread), pas un appel direct dans la coroutine.
    """
    import threading

    thread_appelant = []
    monkeypatch.setattr(
        email_service.resend.Emails,
        "send",
        lambda payload: thread_appelant.append(threading.current_thread().name),
    )

    await email_service.envoyer_email(destinataire="t@example.com", sujet="s", corps_html="c")

    assert thread_appelant[0] != threading.current_thread().name


async def test_une_erreur_resend_nest_pas_avalee_par_le_service(monkeypatch):
    """
    Le docstring de envoyer_email est explicite : ce n'est PAS à ce service
    de décider si un échec d'envoi doit être toléré - c'est à l'appelant
    (chaque routeur encapsule déjà l'appel dans un try/except, section
    13.4). Si ce service avalait lui-même les erreurs, un appelant qui
    voudrait un jour traiter l'échec différemment (ex. retry, alerte) n'en
    aurait plus la possibilité.
    """

    def _echec(payload):
        raise RuntimeError("Resend indisponible")

    monkeypatch.setattr(email_service.resend.Emails, "send", _echec)

    with pytest.raises(RuntimeError, match="Resend indisponible"):
        await email_service.envoyer_email(destinataire="t@example.com", sujet="s", corps_html="c")


async def test_resend_est_configure_avec_la_cle_api_des_settings():
    """La clé API doit être celle de la configuration, pas une valeur codée en dur."""
    assert email_service.resend.api_key == email_service.settings.resend_api_key
    assert email_service.resend.api_key  # non vide


async def test_un_envoi_reussi_est_journalise_en_info(monkeypatch, caplog):
    """
    Ecart identifie et corrige (revue du 26/09) : avant ce correctif, rien
    ne permettait de savoir apres coup, en lisant les logs du conteneur, si
    une notification avait reellement ete envoyee - meme en cas de succes.
    """
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda payload: None)

    with caplog.at_level("INFO", logger="app.services.email_service"):
        await email_service.envoyer_email(
            destinataire="succes@example.com", sujet="Sujet OK", corps_html="<p>c</p>"
        )

    messages = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("succes@example.com" in m and "envoye" in m.lower() for m in messages)


async def test_un_echec_est_journalise_en_error_avec_la_cause(monkeypatch, caplog):
    """
    Le point precis de la demande : les logs doivent dire non seulement
    QU'il y a eu un echec, mais aussi CE QUI l'empeche (message d'exception
    Resend capture via logger.exception - cle API invalide, domaine non
    verifie, destinataire rejete, timeout...), sans que l'appelant
    (except Exception: pass, section 13.4) n'ait besoin de le journaliser
    lui-meme a chacun de ses 4 points d'appel.
    """

    def _echec(payload):
        raise RuntimeError("Domaine d'envoi non verifie aupres de Resend")

    monkeypatch.setattr(email_service.resend.Emails, "send", _echec)

    with caplog.at_level("ERROR", logger="app.services.email_service"):
        with pytest.raises(RuntimeError):
            await email_service.envoyer_email(
                destinataire="echec@example.com", sujet="Sujet KO", corps_html="<p>c</p>"
            )

    erreurs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(erreurs) == 1
    # Le message du logger identifie le destinataire concerne...
    assert "echec@example.com" in erreurs[0].message
    # ...et la cause exacte (capturee automatiquement par logger.exception
    # via exc_info, pas seulement le message generique du logger).
    assert erreurs[0].exc_info is not None
    assert "Domaine d'envoi non verifie" in caplog.text


async def test_en_developpement_sans_cle_resend_le_message_est_affiche_dans_les_logs(monkeypatch, caplog):
    """Installation neuve sans Resend : pas d'envoi, pas d'erreur, et le lien de decision reste recuperable."""
    appels = []
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda payload: appels.append(payload))
    monkeypatch.setattr(email_service.settings, "resend_api_key", "")
    monkeypatch.setattr(email_service.settings, "environment", "development")

    with caplog.at_level("WARNING", logger="app.services.email_service"):
        await email_service.envoyer_email(
            destinataire="dev@example.com", sujet="Sujet dev", corps_html="<a href='/decisions/JETON123'>x</a>"
        )

    assert appels == []
    assert any("JETON123" in r.message and "dev@example.com" in r.message for r in caplog.records)


async def test_en_production_sans_cle_resend_l_envoi_reste_une_erreur(monkeypatch):
    """Le mode « logs » ne doit JAMAIS masquer une cle absente en production."""
    def _echec(payload):
        raise RuntimeError("cle absente")

    monkeypatch.setattr(email_service.resend.Emails, "send", _echec)
    monkeypatch.setattr(email_service.settings, "resend_api_key", "")
    monkeypatch.setattr(email_service.settings, "environment", "production")

    with pytest.raises(RuntimeError, match="cle absente"):
        await email_service.envoyer_email(destinataire="t@example.com", sujet="s", corps_html="c")
