"""
Webhooks HTTP sortants (section 10 du CDC technique).

Implementation minimale mais fonctionnelle : recherche des abonnements actifs
pour le processus et l'evenement concernes, signature HMAC-SHA256 du corps
JSON, envoi via httpx.AsyncClient. Une tentative unique pour l'instant -
le mecanisme complet de nouvelle tentative avec delai croissant (section 10,
"Fiabilite de livraison") reste a implementer via un planificateur dedie.

Un echec d'envoi ne doit jamais faire echouer la transaction principale
(section 13.4) : les exceptions sont capturees, pas propagees.
"""
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chiffrement import chiffrer_secret, dechiffrer_secret
from app.models.abonnement_webhook import AbonnementWebhook
from app.models.enums import EvenementWebhook, TypeProcessus

logger = logging.getLogger(__name__)


def _signer(secret: str, corps: bytes) -> str:
    return hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()


async def notifier_evenement(
    db: AsyncSession,
    demande_id,
    processus: TypeProcessus,
    evenement: EvenementWebhook,
) -> None:
    """Notifie chaque abonnement actif souscrit a cet evenement pour ce processus."""
    resultat = await db.execute(
        select(AbonnementWebhook).where(
            AbonnementWebhook.processus == processus,
            AbonnementWebhook.actif.is_(True),
        )
    )
    abonnements = resultat.scalars().all()

    for abonnement in abonnements:
        if evenement.value not in (abonnement.evenements or []):
            continue

        payload = {
            "evenement": evenement.value,
            "demande_id": str(demande_id),
            "horodatage": datetime.now(UTC).isoformat(),
        }
        corps = json.dumps(payload).encode()
        try:
            secret = dechiffrer_secret(abonnement.secret_hmac)
        except ValueError:
            # Secret illisible (cle changee) : cet abonnement est ignore, les autres continuent.
            # Ne doit jamais faire echouer la transaction principale (CDC 13.4).
            logger.error("Secret illisible pour l'abonnement webhook %s : notification ignoree.", abonnement.id)
            continue
        signature = _signer(secret, corps)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    abonnement.url_destination,
                    content=corps,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature-256": signature,
                    },
                )
        except httpx.HTTPError:
            # TODO: consigner l'echec pour nouvelle tentative avec delai croissant
            # (section 10, "Fiabilite de livraison") plutot que de l'ignorer.
            continue


async def creer_abonnement(
    db: AsyncSession, url_destination: str, secret: str, processus: TypeProcessus, evenements: list[str]
) -> AbonnementWebhook:
    """
    Cree un abonnement en chiffrant son secret avant stockage (R22). Point d'entree a utiliser pour
    toute creation d'abonnement (script, futur routeur d'administration) : n'ecrivez pas
    `secret_hmac` a la main. Ne commit pas.
    """
    abonnement = AbonnementWebhook(
        url_destination=url_destination,
        secret_hmac=chiffrer_secret(secret),
        processus=processus,
        evenements=evenements,
    )
    db.add(abonnement)
    await db.flush()
    return abonnement
