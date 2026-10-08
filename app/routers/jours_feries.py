"""
Routes d'administration du calendrier des jours fériés (écart identifié
suite à la revue comparative avec des plateformes de référence).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import audit
from app.core.dependencies import exiger_roles
from app.models.enums import RoleUtilisateur
from app.models.jour_ferie import JourFerie
from app.schemas.jour_ferie import JourFerieCreate, JourFerieRead

router = APIRouter(prefix="/api/v1/jours-feries", tags=["jours_feries"])


@router.post("/", response_model=JourFerieRead, status_code=201)
async def creer_jour_ferie(
    payload: JourFerieCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    jour_ferie = JourFerie(**payload.model_dump())
    db.add(jour_ferie)
    await db.flush()
    await audit.consigner(
        db, action="jour_ferie_cree", acteur_id=current_user.id, cible_type="jour_ferie",
        cible_id=jour_ferie.id, details={"nom": jour_ferie.nom, "date": str(jour_ferie.date), "recurrent": jour_ferie.recurrent},
    )
    await db.commit()
    await db.refresh(jour_ferie)
    return jour_ferie


@router.get("/", response_model=list[JourFerieRead])
async def lister_jours_feries(db: AsyncSession = Depends(get_db)):
    resultat = await db.execute(select(JourFerie))
    return resultat.scalars().all()
