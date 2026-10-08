"""
Planificateur des rappels automatiques (CDC fonctionnel 2.4).

Une boucle asyncio dans le processus du backend : pas de service externe a
deployer ni a superviser (un cron, un worker Celery...). Plusieurs instances du
backend peuvent la faire tourner en meme temps sans doublon : chaque rappel est
reserve par un UPDATE atomique (voir app/services/rappels.py).
"""
import asyncio
import logging

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services import rappels

logger = logging.getLogger(__name__)
settings = get_settings()


async def une_passe() -> int:
    async with AsyncSessionLocal() as db:
        return await rappels.traiter_rappels(db)


async def boucle(intervalle_secondes: float) -> None:
    while True:
        try:
            envoyes = await une_passe()
            if envoyes:
                logger.info("%d rappel(s) automatique(s) envoye(s)", envoyes)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Une passe en echec ne doit jamais arreter les suivantes.
            logger.exception("Echec d'une passe de rappels automatiques")
        await asyncio.sleep(intervalle_secondes)


def demarrer() -> asyncio.Task | None:
    """Lance la boucle si les rappels sont actives ; None sinon."""
    if not settings.rappels_automatiques_actifs or settings.rappel_frequence_heures <= 0:
        logger.info("Rappels automatiques desactives.")
        return None
    intervalle = max(1.0, settings.rappel_verification_minutes * 60)
    logger.info(
        "Rappels automatiques actifs : frequence %s h, controle toutes les %.0f s.",
        settings.rappel_frequence_heures,
        intervalle,
    )
    return asyncio.create_task(boucle(intervalle), name="rappels-automatiques")
