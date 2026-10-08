"""
Consultation du journal d'audit (CDC fonctionnel 2.4 : traçabilité "qui a fait quoi, et quand").

Jusqu'ici aucune route ne lisait le journal : il était inaltérable dans l'intention, invisible
dans les faits. Réservé aux rôles de contrôle : DRH, Direction générale, Contrôleur de gestion.
Lecture seule : rien ici ne modifie le journal.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import exiger_roles, get_current_user
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur
from app.schemas.audit import ActionAudit, AuditPage, HistoriqueEntree
from app.services import audit, pieces
from app.models.demande import Demande

router = APIRouter(prefix="/api/v1", tags=["audit"])

ROLES_CONTROLE = (RoleUtilisateur.DRH, RoleUtilisateur.DIRECTION_GENERALE, RoleUtilisateur.CONTROLEUR_DE_GESTION)


@router.get("/audit/", response_model=AuditPage)
async def consulter_le_journal(
    action: str | None = None,
    acteur_id: uuid.UUID | None = None,
    cible_type: str | None = None,
    cible_id: uuid.UUID | None = None,
    depuis: datetime | None = Query(None, description="Horodatage minimal (inclus)."),
    jusqu_a: datetime | None = Query(None, description="Horodatage maximal (inclus)."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: Utilisateur = Depends(exiger_roles(*ROLES_CONTROLE)),
):
    total, elements = await audit.rechercher(
        db, action=action, acteur_id=acteur_id, cible_type=cible_type, cible_id=cible_id,
        depuis=depuis, jusqu_a=jusqu_a, limit=limit, offset=offset,
    )
    return AuditPage(total=total, limit=limit, offset=offset, elements=elements)


@router.get("/audit/actions", response_model=list[ActionAudit])
async def lister_les_actions(_current_user: Utilisateur = Depends(exiger_roles(*ROLES_CONTROLE))):
    """Actions connues et leur libellé, pour alimenter le filtre de l'écran."""
    return [ActionAudit(action=a, libelle=l) for a, l in sorted(audit.LIBELLES.items(), key=lambda x: x[1])]


@router.get("/demandes/{demande_id}/historique", response_model=list[HistoriqueEntree])
async def historique_du_dossier(
    demande_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Chronologie du dossier pour ses participants (demandeur, DRH, approbateurs de la demande)."""
    try:
        identifiant = uuid.UUID(demande_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    demande = await db.get(Demande, identifiant)
    if demande is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    if not await pieces.peut_consulter_demande(db, demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cet historique.")
    return await audit.historique_demande(db, demande)
