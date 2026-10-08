"""
Point d'entree de l'application FastAPI (section 3.2 du CDC technique).

Les routeurs orchestrent uniquement l'appel aux services et la conversion
entre schemas et modeles ; toute la logique metier vit dans app/services.
"""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.services import planificateur, stockage_fichiers
from app.routers import (
    achats,
    audit,
    auth,
    budget,
    clarifications,
    conges,
    dashboard,
    decisions,
    devises,
    jours_feries,
    notes_frais,
    pieces_jointes,
    synthese_frais,
    types_conge,
    utilisateurs,
)

# Ecart identifie et corrige (revue du 26/09) : aucune configuration de
# logging n'existait dans tout le backend - un logger.info()/logger.error()
# ailleurs dans le code (voir app/services/email_service.py) restait
# invisible sans ceci, le logger racine de Python etant a WARNING par
# defaut. Sortie sur stderr (comportement par defaut de basicConfig, et
# celui deja utilise par uvicorn/gunicorn) - capturee comme le reste des
# logs du conteneur (NubieCloud ou tout autre hebergeur).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

settings = get_settings()

logger_startup = logging.getLogger(__name__)
if not settings.resend_api_key:
    # Ecart trouve et corrige (revue du 27/09) : le README affirmait a tort
    # qu'un demarrage sans RESEND_API_KEY "echoue au chargement de la
    # configuration" - faux, ce champ a une valeur par defaut vide
    # (deliberement, pour ne pas bloquer le developpement local, voir
    # app/services/email_service.py). Sans ce log, un oubli en production
    # ne se manifeste que bien plus tard, au premier envoi reel echoue,
    # avec une erreur Resend peu explicite (voir logger.exception dans
    # email_service.py) - plutot que d'etre visible des le demarrage.
    logger_startup.warning(
        "RESEND_API_KEY n'est pas definie : tout envoi d'e-mail (decision, "
        "invitation, reinitialisation de mot de passe) echouera silencieusement "
        "cote appelant, mais sera journalise en ERROR par app.services.email_service. "
        "Normal en developpement local ; a corriger avant une mise en production."
    )

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Demarre les rappels automatiques (CDC 2.4) et les arrete proprement a l'extinction."""
    # Stockage des pieces jointes : une configuration S3 INCOMPLETE arrete le demarrage (sinon les fichiers
    # partiraient en silence sur un disque ephemere) ; sinon on journalise le mode actif (jamais de secret).
    logging.getLogger(__name__).info("Stockage des pieces jointes : %s", stockage_fichiers.description_stockage())
    tache = planificateur.demarrer()
    try:
        yield
    finally:
        if tache is not None:
            tache.cancel()
            with suppress(asyncio.CancelledError):
                await tache


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version="0.1.0",
    description="Backend FastAPI - automatisation des processus métiers "
                 "(congés, notes de frais, achats & contrats).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(conges.router)
app.include_router(notes_frais.router)
app.include_router(budget.router)
app.include_router(clarifications.router)
app.include_router(pieces_jointes.router)
app.include_router(audit.router)
app.include_router(devises.router)
app.include_router(devises.router_taux)
app.include_router(synthese_frais.router)
app.include_router(achats.router)
app.include_router(decisions.router)
app.include_router(dashboard.router)
app.include_router(types_conge.router)
app.include_router(jours_feries.router)
app.include_router(utilisateurs.router)


@app.get("/health", tags=["monitoring"])
async def health_check():
    """Endpoint de supervision (utilisable par NubieCloud Status, section 14.1)."""
    return {"status": "ok", "app": settings.app_name}
