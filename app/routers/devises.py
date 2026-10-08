"""
Devises et taux de change (decision du 28/09 : "plusieurs devises avec conversion").

- Lecture des devises utilisables et conversion a la demande : tout utilisateur connecte (les formulaires
  de note de frais et d'achat en ont besoin pour montrer l'equivalent avant l'envoi).
- Gestion des taux : roles financiers (DRH, Controleur de gestion, Direction financiere) - un taux conditionne
  ce qui sera debite d'une enveloppe budgetaire ; chaque modification est consignee au journal d'audit.
"""
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import exiger_roles, get_current_user
from app.models.enums import RoleUtilisateur
from app.models.taux_change import TauxChange
from app.models.user import Utilisateur
from app.schemas.devises import ConversionRead, DeviseRead, DevisesRead, TauxChangeDefinir, TauxChangeRead
from app.services import audit, devises

router = APIRouter(prefix="/api/v1/devises", tags=["devises"])
router_taux = APIRouter(prefix="/api/v1/taux-change", tags=["devises"])

ROLES_TAUX = (RoleUtilisateur.DRH, RoleUtilisateur.CONTROLEUR_DE_GESTION, RoleUtilisateur.DIRECTION_FINANCIERE)


def _aujourdhui() -> date:
    return datetime.now(UTC).date()


@router.get("/", response_model=DevisesRead)
async def lister_les_devises(
    db: AsyncSession = Depends(get_db), _current_user: Utilisateur = Depends(get_current_user)
):
    """La devise de reference et chaque devise disposant d'un taux applicable aujourd'hui."""
    reference = devises.devise_reference()
    codes = (await db.execute(select(TauxChange.devise).distinct().order_by(TauxChange.devise))).scalars().all()
    utilisables = []
    for code in codes:
        if code == reference:
            continue
        applicable = await devises.taux_applicable(db, code, _aujourdhui())
        if applicable:
            utilisables.append(DeviseRead(code=code, taux=float(applicable[0]), date_effet=applicable[1]))
    return DevisesRead(reference=reference, devises=[DeviseRead(code=reference, taux=1.0, date_effet=None), *utilisables])


@router.get("/convertir", response_model=ConversionRead)
async def convertir_un_montant(
    montant: float = Query(..., gt=0),
    devise: str = Query(..., min_length=3, max_length=3),
    a_la_date: date | None = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
    _current_user: Utilisateur = Depends(get_current_user),
):
    """Equivalent dans la devise de reference, au taux qui serait applique a cette date (apercu des formulaires)."""
    try:
        c = await devises.convertir(db, montant, devise, a_la_date or _aujourdhui())
    except devises.TauxIntrouvable as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ConversionRead(devise=c.devise, devise_reference=devises.devise_reference(), taux=c.taux,
                          montant=c.montant, montant_reference=c.montant_reference, date_effet=c.date_effet)


def _lecture(t: TauxChange) -> TauxChangeRead:
    return TauxChangeRead(id=str(t.id), devise=t.devise, taux=float(t.taux), date_effet=t.date_effet)


@router_taux.get("/", response_model=list[TauxChangeRead])
async def lister_les_taux(
    db: AsyncSession = Depends(get_db), _current_user: Utilisateur = Depends(exiger_roles(*ROLES_TAUX))
):
    """Historique complet, du plus recent au plus ancien."""
    lignes = (
        await db.execute(select(TauxChange).order_by(TauxChange.date_effet.desc(), TauxChange.devise))
    ).scalars().all()
    return [_lecture(t) for t in lignes]


@router_taux.put("/", response_model=TauxChangeRead)
async def definir_un_taux(
    payload: TauxChangeDefinir,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(*ROLES_TAUX)),
):
    """Cree le taux (devise, date d'effet) ou le corrige (idempotent). N'affecte jamais une demande deja soumise."""
    if payload.devise == devises.devise_reference():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{payload.devise} est la devise de référence : son taux est toujours 1.",
        )
    existant = (
        await db.execute(
            select(TauxChange).where(TauxChange.devise == payload.devise, TauxChange.date_effet == payload.date_effet)
        )
    ).scalar_one_or_none()
    taux_avant = float(existant.taux) if existant else None
    if existant is None:
        existant = TauxChange(devise=payload.devise, taux=payload.taux, date_effet=payload.date_effet,
                              defini_par_id=current_user.id)
        db.add(existant)
        await db.flush()
    else:
        existant.taux = payload.taux
        existant.defini_par_id = current_user.id
    await audit.consigner(
        db, action="taux_change_defini", acteur_id=current_user.id, cible_type="taux_change", cible_id=existant.id,
        details={"devise": payload.devise, "date_effet": str(payload.date_effet),
                 "taux_avant": taux_avant, "taux_apres": payload.taux},
    )
    await db.commit()
    await db.refresh(existant)
    return _lecture(existant)
