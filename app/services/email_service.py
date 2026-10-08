"""
Interface d'envoi d'e-mails (section 14.2).

Point d'abstraction unique : le moteur de routage, les jetons de décision et
le module de webhooks ignorent totalement quel fournisseur est actif
derrière cette interface (Figure 2 du CDC technique). Fournisseur retenu :
Resend (décision confirmée), appelé en thread separe car son SDK est
synchrone, pour ne pas bloquer la boucle d'evenements asyncio.

Écart identifié et corrigé (revue du 26/09) : les appelants encapsulent cet
appel dans un `except Exception: pass` (section 13.4 - un e-mail qui échoue
ne doit jamais faire échouer la transaction principale), ce qui avalait
l'exception sans aucune trace. Impossible jusqu'ici de savoir, après coup,
si une notification avait réellement été envoyée ou pourquoi elle avait
échoué (clé API invalide, domaine non vérifié, destinataire rejeté,
timeout réseau...). Le succès et l'échec sont maintenant journalisés ici,
au même endroit du code que gère déjà chaque appelant - qui en bénéficie
automatiquement sans dupliquer de logging à ses 4 points d'appel
(app/routers/auth.py, conges.py, decisions.py, utilisateurs.py).
"""
import asyncio
import base64
import logging

import resend

from app.core.config import get_settings
from app.services import email_gabarit

settings = get_settings()
resend.api_key = settings.resend_api_key

logger = logging.getLogger(__name__)


async def envoyer_email(
    destinataire: str, sujet: str, corps_html: str, pieces_jointes: list[tuple[str, bytes]] | None = None
) -> None:
    """
    Envoie un e-mail via Resend.

    Ne doit jamais faire échouer la transaction principale de l'appelant
    (section 13.4) : c'est à l'appelant de décider s'il encapsule cet appel
    dans un try/except (voir app/routers/conges.py pour un exemple) - cette
    fonction relance systématiquement l'exception après l'avoir journalisée,
    pour ne rien changer au comportement déjà en place côté appelants.

    `pieces_jointes` : liste optionnelle de (nom de fichier, octets). Le plafond de taille (40 Mo par e-mail chez
    Resend, base64 compris) est géré en amont par app/services/pieces_email.py, qui décide quelles pièces joindre.
    """
    # Developpement SANS Resend (cle vide) : aucun envoi n'est tente ; le message complet (donc les liens de
    # decision et d'activation) est affiche dans les logs de l'API (`docker compose logs api`), ce qui permet de
    # suivre un circuit apres une installation neuve. Jamais en production : la, une cle absente reste une erreur.
    if not settings.resend_api_key and settings.environment.lower() == "development":
        logger.warning(
            "[DEV] E-mail NON envoye (RESEND_API_KEY vide) - a : %s | sujet : %s | pieces jointes : %s\n%s",
            destinataire, sujet, [nom for nom, _ in pieces_jointes or []] or "aucune", corps_html,
        )
        return

    # Habillage commun (en-tete de marque, titre = sujet, pied de page) : les appelants ne fournissent que le contenu.
    payload = {
        "from": settings.email_from,
        "to": [destinataire],
        "subject": sujet,
        "html": email_gabarit.envelopper(sujet, corps_html),
    }
    if pieces_jointes:
        # Format Resend (documentation "Attachments") : `filename` + `content` en base64.
        payload["attachments"] = [
            {"filename": nom, "content": base64.b64encode(octets).decode("ascii")} for nom, octets in pieces_jointes
        ]
    try:
        await asyncio.to_thread(resend.Emails.send, payload)
    except Exception:
        # logger.exception capture automatiquement le type d'exception, son
        # message et la pile d'appels complete - c'est precisement "ce qui
        # empeche" l'envoi (cle API Resend invalide, domaine d'envoi non
        # verifie, destinataire rejete, timeout reseau...), sans avoir a
        # deviner apres coup.
        logger.exception(
            "Echec d'envoi d'e-mail a %s (sujet : %s)", destinataire, sujet
        )
        raise
    else:
        logger.info("E-mail envoye avec succes a %s (sujet : %s)", destinataire, sujet)
