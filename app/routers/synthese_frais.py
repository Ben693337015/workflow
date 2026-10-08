"""
Synthese des notes de frais validees (CDC fonctionnel 3 : "tableau de synthese des frais valides transmis a
la comptabilite pour remboursement") : ecran et export CSV. L'e-mail a chaque validation est envoye par
app/routers/decisions.py avec la meme construction de ligne (app/services/synthese_frais.py).

Reserve a la DRH, a la Direction financiere et au Controleur de gestion.
"""
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import exiger_roles
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur
from app.schemas.synthese_frais import SyntheseFrais
from app.services import audit, synthese_frais

router = APIRouter(prefix="/api/v1/notes-frais", tags=["notes-frais"])

ROLES_SYNTHESE = (RoleUtilisateur.DRH, RoleUtilisateur.DIRECTION_FINANCIERE, RoleUtilisateur.CONTROLEUR_DE_GESTION)


@router.get("/synthese", response_model=SyntheseFrais)
async def synthese_des_notes_de_frais(
    depuis: date | None = Query(None, description="Validee a partir de cette date (incluse)."),
    jusqu_a: date | None = Query(None, description="Validee jusqu'a cette date (incluse)."),
    service: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: Utilisateur = Depends(exiger_roles(*ROLES_SYNTHESE)),
):
    return await synthese_frais.rechercher(db, depuis=depuis, jusqu_a=jusqu_a, service=service, limit=limit, offset=offset)


@router.get("/synthese.csv")
async def exporter_la_synthese(
    depuis: date | None = None,
    jusqu_a: date | None = None,
    service: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(*ROLES_SYNTHESE)),
):
    """Export CSV de TOUTES les notes correspondant aux criteres (pas seulement la page affichee)."""
    lignes, tronque = await synthese_frais.toutes_les_lignes(db, depuis=depuis, jusqu_a=jusqu_a, service=service)
    # Un export de donnees personnelles et financieres est une action a tracer (qui, quand, quels criteres).
    await audit.consigner(
        db, action="synthese_frais_exportee", acteur_id=current_user.id, cible_type="synthese_frais", cible_id=None,
        details={"depuis": str(depuis) if depuis else None, "jusqu_a": str(jusqu_a) if jusqu_a else None,
                 "service": service, "lignes": len(lignes), "tronque": tronque},
    )
    await db.commit()
    nom = f"synthese-notes-de-frais-{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return Response(
        content=synthese_frais.contenu_csv(lignes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )
