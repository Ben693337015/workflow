"""
Routes des enveloppes budgétaires (section 4 / 11 du CDC technique).

Sans ce routeur, le suivi budgétaire (app/services/extensions/suivi_budgetaire.py)
serait inutilisable en pratique : aucun moyen d'allouer un budget à un
service, donc toute note de frais serait bloquée à 0 EUR disponible.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from app.core.database import get_db
from app.core.dependencies import exiger_roles
from app.models.enums import RoleUtilisateur
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.user import Utilisateur
from app.schemas.budget import EnveloppeBudgetaireCreate, EnveloppeBudgetaireRead
from app.services import audit
from app.services.extensions import suivi_budgetaire

router = APIRouter(prefix="/api/v1/enveloppes-budgetaires", tags=["budget"])


def _vers_lecture(enveloppe: EnveloppeBudgetaire) -> EnveloppeBudgetaireRead:
    return EnveloppeBudgetaireRead(
        id=enveloppe.id,
        service=enveloppe.service,
        exercice=enveloppe.exercice,
        budget_alloue=float(enveloppe.budget_alloue),
        budget_consomme=float(enveloppe.budget_consomme),
        solde_disponible=float(enveloppe.budget_alloue) - float(enveloppe.budget_consomme),
    )


@router.get("/", response_model=list[EnveloppeBudgetaireRead])
async def lister_enveloppes(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(
        exiger_roles(RoleUtilisateur.DRH, RoleUtilisateur.CONTROLEUR_DE_GESTION)
    ),
):
    resultat = await db.execute(select(EnveloppeBudgetaire).order_by(EnveloppeBudgetaire.service))
    return [_vers_lecture(e) for e in resultat.scalars().all()]


@router.put("/", response_model=EnveloppeBudgetaireRead)
async def definir_enveloppe(
    payload: EnveloppeBudgetaireCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(
        exiger_roles(RoleUtilisateur.DRH, RoleUtilisateur.CONTROLEUR_DE_GESTION)
    ),
):
    """
    Cree l'enveloppe si elle n'existe pas encore pour ce service/exercice,
    ou met a jour son budget alloue sinon (idempotent, meme principe que
    PUT /api/v1/utilisateurs/{id}/soldes-conges pour les conges) -
    `budget_consomme` n'est jamais touche par cette route : uniquement par
    suivi_budgetaire.consommer_budget, a l'approbation finale d'une depense.
    """
    enveloppe = await suivi_budgetaire.obtenir_enveloppe(db, payload.service, payload.exercice)
    budget_avant = float(enveloppe.budget_alloue) if enveloppe is not None else None
    if enveloppe is None:
        enveloppe = EnveloppeBudgetaire(
            service=payload.service, exercice=payload.exercice, budget_alloue=payload.budget_alloue
        )
        db.add(enveloppe)
        await db.flush()
    else:
        enveloppe.budget_alloue = payload.budget_alloue

    # Le budget alloue conditionne l'autorisation des depenses (CDC 4.3) : toute modification
    # doit pouvoir etre retrouvee (avant / apres, auteur, horodatage).
    await audit.consigner(
        db, action="enveloppe_budgetaire_definie", acteur_id=current_user.id,
        cible_type="enveloppe_budgetaire", cible_id=enveloppe.id,
        details={
            "service": payload.service, "exercice": payload.exercice,
            "budget_alloue_avant": budget_avant, "budget_alloue_apres": float(payload.budget_alloue),
        },
    )
    await db.commit()
    await db.refresh(enveloppe)
    return _vers_lecture(enveloppe)
