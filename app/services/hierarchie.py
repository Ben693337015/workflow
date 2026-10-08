"""
Hierarchie manager -> collaborateurs, geree par la DRH.

Deux besoins du metier (05/10) : changer le manager d'un employe, et en donner un a un compte qui n'en a
pas. Le routage des conges et des notes de frais envoie la demande au `manager_id` du demandeur
(routing_engine) ; un rattachement incorrect ou absent bloque donc la soumission ("Aucun manager rattache").

Regles :
- le manager doit exister, etre actif, ne pas etre l'employe lui-meme et ne pas avoir de role "employe" ;
- aucune boucle : on ne peut pas rattacher quelqu'un a l'un de ses propres subordonnes (directs ou non) ;
- une demande deja EN COURS de decision chez l'ancien manager est transmise au nouveau (sinon elle resterait
  bloquee chez quelqu'un qui n'est plus responsable de l'employe) ;
- retirer le manager d'un employe dont une demande attend la decision de l'ancien manager est refuse
  (la demande n'aurait plus d'approbateur) : il faut d'abord designer un remplacant.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demande import Demande
from app.models.enums import RoleUtilisateur, StatutDemande, StatutEtape
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur

STATUTS_ETAPE_OUVERTE = (StatutEtape.EN_ATTENTE, StatutEtape.EN_COURS)
STATUTS_DEMANDE_OUVERTE = (StatutDemande.EN_COURS, StatutDemande.COMPLEMENT_DEMANDE)


class ManagerInvalide(ValueError):
    """Rattachement refuse ; le message est destine a l'utilisateur."""


async def valider_manager(db: AsyncSession, employe_id: uuid.UUID | None, manager_id: uuid.UUID) -> Utilisateur:
    """`employe_id` est None a la creation d'un compte (il n'a encore ni subordonnes ni identifiant)."""
    if employe_id is not None and manager_id == employe_id:
        raise ManagerInvalide("Un utilisateur ne peut pas être son propre manager.")
    manager = await db.get(Utilisateur, manager_id)
    if manager is None:
        raise ManagerInvalide("Le manager indiqué est introuvable.")
    if not manager.actif:
        raise ManagerInvalide("Ce compte est désactivé : il ne peut pas devenir manager.")
    if manager.role == RoleUtilisateur.EMPLOYE:
        raise ManagerInvalide("Un compte au rôle « Employé » ne peut pas être désigné comme manager.")

    # Remontee de la chaine hierarchique du futur manager : si on retombe sur l'employe, ce serait une boucle.
    if employe_id is not None:
        courant, vus = manager, {manager.id}
        while courant.manager_id is not None:
            if courant.manager_id == employe_id:
                raise ManagerInvalide(
                    "Ce rattachement créerait une boucle : ce manager dépend déjà (directement ou non) de cet employé."
                )
            if courant.manager_id in vus:  # boucle preexistante sans rapport avec l'employe : on s'arrete
                break
            vus.add(courant.manager_id)
            suivant = await db.get(Utilisateur, courant.manager_id)
            if suivant is None:
                break
            courant = suivant
    return manager


async def etapes_ouvertes_chez(db: AsyncSession, employe_id: uuid.UUID, approbateur_id: uuid.UUID):
    """Etapes encore ouvertes, sur des demandes de `employe_id`, attendues de `approbateur_id`."""
    resultat = await db.execute(
        select(EtapeWorkflow, Demande)
        .join(Demande, Demande.id == EtapeWorkflow.demande_id)
        .where(
            Demande.demandeur_id == employe_id,
            Demande.statut_global.in_(STATUTS_DEMANDE_OUVERTE),
            EtapeWorkflow.statut.in_(STATUTS_ETAPE_OUVERTE),
            EtapeWorkflow.approbateur_attendu_id == approbateur_id,
        )
    )
    return list(resultat.all())


async def reaffecter_etapes(
    db: AsyncSession, employe_id: uuid.UUID, ancien_id: uuid.UUID, nouveau_id: uuid.UUID
) -> list[tuple[EtapeWorkflow, Demande]]:
    """Transmet au nouveau manager les etapes ouvertes de l'employe (sans commit : l'appelant valide)."""
    paires = await etapes_ouvertes_chez(db, employe_id, ancien_id)
    for etape, _demande in paires:
        etape.approbateur_attendu_id = nouveau_id
    return paires
