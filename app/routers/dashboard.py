"""Route du tableau de bord de suivi (section 12)."""
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/")
async def lister_demandes():
    """TODO: filtrage par statut, avec etat de livraison des webhooks associes."""
    # Ecart identifie et corrige (revue du 15/09) : voir achats.py, meme raison.
    # Un tableau de bord "Mes demandes" fonctionnel existe deja pour les conges
    # (GET /api/v1/conges/) ; cette route generique multi-processus reste a faire
    # (Phase 2/3, ROADMAP).
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Tableau de bord générique non encore implémenté (Phase 2/3).",
    )
