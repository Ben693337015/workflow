"""
Routes d'administration des types de congé (écart identifié : nécessaire
pour que le formulaire de demande référence un type structuré plutôt
qu'une chaîne libre).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import audit
from app.core.dependencies import exiger_roles
from app.models.enums import RoleUtilisateur
from app.models.type_conge import TypeConge
from app.schemas.type_conge import TypeCongeCreate, TypeCongeRead

router = APIRouter(prefix="/api/v1/types-conge", tags=["types_conge"])


@router.post("/", response_model=TypeCongeRead, status_code=201)
async def creer_type_conge(
    payload: TypeCongeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    resultat = await db.execute(select(TypeConge).where(TypeConge.code == payload.code))
    if resultat.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce code de type de congé existe déjà.")
    type_conge = TypeConge(**payload.model_dump())
    db.add(type_conge)
    await db.flush()
    await audit.consigner(
        db, action="type_conge_cree", acteur_id=current_user.id, cible_type="type_conge",
        cible_id=type_conge.id, details={"code": type_conge.code, "nom": type_conge.nom},
    )
    await db.commit()
    await db.refresh(type_conge)
    return type_conge


@router.get("/", response_model=list[TypeCongeRead])
async def lister_types_conge(
    db: AsyncSession = Depends(get_db),
    inclure_inactifs: bool = False,
):
    """
    Par défaut, ne renvoie que les types actifs (c'est ce que le formulaire
    de demande de congé doit proposer). `inclure_inactifs=true` est réservé
    à l'écran d'administration (la DRH doit pouvoir retrouver et réactiver
    un type qu'elle a désactivé par erreur) - vérifié explicitement plutôt
    que d'exposer silencieusement les types désactivés à tout le monde.
    """
    requete_sql = select(TypeConge)
    if not inclure_inactifs:
        requete_sql = requete_sql.where(TypeConge.actif.is_(True))
    resultat = await db.execute(requete_sql)
    return resultat.scalars().all()


@router.post("/{type_conge_id}/desactiver", response_model=TypeCongeRead)
async def desactiver_type_conge(
    type_conge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    """
    Écart identifié (revue du 17/09) : "supprimer un type de congé" est
    implémenté en désactivation (soft-delete), jamais en suppression
    physique - un type déjà référencé par des demandes soumises ou des
    soldes existants ne peut pas être supprimé sans casser l'historique et
    l'intégrité référentielle (donnees JSONB des demandes, FK de
    soldes_conges). Désactivé, il disparaît immédiatement du formulaire de
    demande (lister_types_conge, ci-dessus) sans toucher à l'existant.
    """
    type_conge = await db.get(TypeConge, type_conge_id)
    if type_conge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Type de congé introuvable.")
    type_conge.actif = False
    await audit.consigner(
        db, action="type_conge_desactive", acteur_id=current_user.id, cible_type="type_conge",
        cible_id=type_conge.id, details={"code": type_conge.code},
    )
    await db.commit()
    await db.refresh(type_conge)
    return type_conge


@router.post("/{type_conge_id}/reactiver", response_model=TypeCongeRead)
async def reactiver_type_conge(
    type_conge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    type_conge = await db.get(TypeConge, type_conge_id)
    if type_conge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Type de congé introuvable.")
    type_conge.actif = True
    await audit.consigner(
        db, action="type_conge_reactive", acteur_id=current_user.id, cible_type="type_conge",
        cible_id=type_conge.id, details={"code": type_conge.code},
    )
    await db.commit()
    await db.refresh(type_conge)
    return type_conge
