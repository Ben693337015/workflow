"""
Extension native n2 : verrou RH sur les congés (section 4.2 / 11 du CDC technique).

Modele du solde (CDC 11.1, correction R17) :

- SOUMISSION : le solde est verifie ET RESERVE dans la meme transaction que la creation
  de la demande, avec un verrou de ligne (`SELECT ... FOR UPDATE`) sur la ligne de solde
  de l'employe. Deux soumissions simultanees sont serialisees par la base : la seconde
  voit le solde deja decremente par la premiere. Avant cette correction, le solde etait
  seulement lu : deux demandes rapprochees passaient toutes deux le controle.
- REFUS, ANNULATION, MODIFICATION : la reservation est liberee (jours rendus au solde).
- APPROBATION : la reservation est confirmee (jours reserves -> jours pris).
- Chaque variation du solde disponible ecrit un mouvement dans `mouvements_conges`.

Duree : jours calendaires inclusifs moins les jours feries declares ; l'exclusion des
week-ends est disponible par reglage (`conges_exclure_weekends`, R20) en attendant la
validation de la regle par la DRH.

Compatibilite : une demande creee AVANT cette correction n'a aucune reservation
enregistree. A son approbation, elle est consommee directement (ancien comportement) et
le mouvement correspondant est ecrit ; a son refus ou son annulation, il n'y a rien a rendre.
"""
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import MotifMouvementConges
from app.models.mouvement_conges import MouvementConges
from app.models.solde_conges import SoldeConges
from app.models.user import Utilisateur
from app.services.calendrier import compter_jours_deductibles


def calculer_duree_en_jours(date_debut: date, date_fin: date) -> int:
    """Nombre de jours calendaires entiers couverts par la demande (bornes incluses)."""
    return (date_fin - date_debut).days + 1


async def calculer_duree_deductible(db: AsyncSession, date_debut: date, date_fin: date) -> int:
    """Durée à imputer sur le solde : jours calendaires moins les jours fériés (et week-ends si réglé)."""
    return await compter_jours_deductibles(
        db, date_debut, date_fin, exclure_weekends=get_settings().conges_exclure_weekends
    )


async def obtenir_solde(
    db: AsyncSession, utilisateur_id, type_conge_id, exercice: int, *, verrouiller: bool = False
) -> SoldeConges | None:
    """
    Recupere la ligne de solde de l'utilisateur pour ce type de congé et cet exercice.

    `verrouiller=True` prend un verrou de ligne (`SELECT ... FOR UPDATE`) jusqu'a la fin de la
    transaction : c'est ce qui serialise deux operations concurrentes sur le meme solde.
    """
    requete = select(SoldeConges).where(
        SoldeConges.utilisateur_id == utilisateur_id,
        SoldeConges.type_conge_id == type_conge_id,
        SoldeConges.exercice == exercice,
    )
    if verrouiller:
        requete = requete.with_for_update().execution_options(populate_existing=True)
    resultat = await db.execute(requete)
    return resultat.scalar_one_or_none()


async def solde_suffisant(
    db: AsyncSession,
    utilisateur: Utilisateur,
    type_conge_id,
    date_debut: date,
    date_fin: date,
) -> tuple[bool, int, float]:
    """
    Vérifie si le solde de l'utilisateur (pour ce type de congé) couvre la
    durée déductible de la demande (jours fériés exclus).

    Retourne (solde_ok, nombre_jours_deductibles, solde_disponible). Un solde
    absent (aucune ligne pour ce type/exercice) est traité comme 0 jour.
    """
    nombre_jours = await calculer_duree_deductible(db, date_debut, date_fin)
    exercice = date_debut.year
    solde = await obtenir_solde(db, utilisateur.id, type_conge_id, exercice)
    solde_disponible = float(solde.solde_jours) if solde else 0.0

    return solde_disponible >= nombre_jours, nombre_jours, solde_disponible


def _ecrire_mouvement(
    db: AsyncSession, utilisateur_id, type_conge_id, exercice: int, demande_id, delta: float, motif
) -> None:
    db.add(
        MouvementConges(
            utilisateur_id=utilisateur_id,
            type_conge_id=type_conge_id,
            exercice=exercice,
            demande_id=demande_id,
            delta=delta,
            motif=motif,
        )
    )


async def reserver_solde(
    db: AsyncSession,
    utilisateur_id,
    type_conge_id,
    exercice: int,
    nombre_jours: float,
    demande_id,
) -> tuple[bool, float]:
    """
    Verifie puis reserve `nombre_jours` sur le solde, sous verrou de ligne (R17).

    Retourne (reservation_faite, solde_disponible_avant). Si le solde est insuffisant, rien n'est
    ecrit : l'appelant doit annuler sa transaction et refuser la demande. Un solde absent est
    traite comme 0 jour. Ne commit pas : meme transaction que la creation de la demande.
    """
    if nombre_jours <= 0:
        return True, 0.0
    solde = await obtenir_solde(db, utilisateur_id, type_conge_id, exercice, verrouiller=True)
    disponible = float(solde.solde_jours) if solde else 0.0
    if solde is None or disponible < nombre_jours:
        return False, disponible

    solde.solde_jours = disponible - nombre_jours
    solde.jours_reserves = float(solde.jours_reserves) + nombre_jours
    _ecrire_mouvement(
        db, utilisateur_id, type_conge_id, exercice, demande_id, -nombre_jours, MotifMouvementConges.RESERVATION
    )
    await db.flush()
    return True, disponible


@dataclass(frozen=True)
class Reservation:
    utilisateur_id: uuid.UUID
    type_conge_id: uuid.UUID
    exercice: int
    jours: float


async def reservation_en_cours(db: AsyncSession, demande_id) -> Reservation | None:
    """
    Jours actuellement reserves pour une demande, deduits de ses mouvements (source de verite).

    Une demande creee avant la correction R17 n'a aucun mouvement : retourne None.
    """
    resultat = await db.execute(select(MouvementConges).where(MouvementConges.demande_id == demande_id))
    totaux: dict[tuple, float] = {}
    for mouvement in resultat.scalars().all():
        cle = (mouvement.utilisateur_id, mouvement.type_conge_id, mouvement.exercice)
        totaux[cle] = totaux.get(cle, 0.0) + float(mouvement.delta)
    for (utilisateur_id, type_conge_id, exercice), net in totaux.items():
        if net < 0:
            return Reservation(utilisateur_id, type_conge_id, exercice, -net)
    return None


async def liberer_reservation(db: AsyncSession, demande, motif: MotifMouvementConges) -> float:
    """
    Rend au solde les jours reserves par une demande (refus, annulation, modification).

    Retourne le nombre de jours rendus (0 si la demande n'avait aucune reservation : demande
    anterieure a la correction, ou congé sans jour deductible). Ne commit pas.
    """
    reservation = await reservation_en_cours(db, demande.id)
    if reservation is None:
        return 0.0
    solde = await obtenir_solde(
        db, reservation.utilisateur_id, reservation.type_conge_id, reservation.exercice, verrouiller=True
    )
    if solde is None:
        return 0.0
    solde.solde_jours = float(solde.solde_jours) + reservation.jours
    solde.jours_reserves = max(float(solde.jours_reserves) - reservation.jours, 0.0)
    _ecrire_mouvement(
        db, reservation.utilisateur_id, reservation.type_conge_id, reservation.exercice,
        demande.id, reservation.jours, motif,
    )
    await db.flush()
    return reservation.jours


async def confirmer_reservation(db: AsyncSession, demande) -> None:
    """
    A l'approbation finale : les jours reserves deviennent des jours pris.

    Le solde disponible ne change pas (il a ete decremente a la soumission), donc aucun
    mouvement n'est ecrit. Pour une demande anterieure a la correction R17 (aucune reservation),
    les jours sont consommes directement, comme avant, avec leur mouvement. Ne commit pas :
    meme transaction que la mise a jour de l'etape de workflow (R18).
    """
    reservation = await reservation_en_cours(db, demande.id)
    if reservation is not None:
        solde = await obtenir_solde(
            db, reservation.utilisateur_id, reservation.type_conge_id, reservation.exercice, verrouiller=True
        )
        if solde is None:
            return
        solde.jours_reserves = max(float(solde.jours_reserves) - reservation.jours, 0.0)
        solde.jours_pris = float(solde.jours_pris) + reservation.jours
        await db.flush()
        return

    date_debut = date.fromisoformat(demande.donnees["date_debut"])
    date_fin = date.fromisoformat(demande.donnees["date_fin"])
    nombre_jours = await calculer_duree_deductible(db, date_debut, date_fin)
    await consommer_solde(
        db, demande.demandeur_id, uuid.UUID(demande.donnees["type_conge_id"]), date_debut.year,
        nombre_jours, demande_id=demande.id,
    )


async def consommer_solde(
    db: AsyncSession, utilisateur_id, type_conge_id, exercice: int, nombre_jours: float, demande_id=None
) -> None:
    """
    Consommation DIRECTE (sans reservation prealable) : decremente le solde disponible et
    incremente les jours pris, avec son mouvement. Reserve aux demandes anterieures a la
    correction R17 ; le circuit courant passe par reserver_solde puis confirmer_reservation.

    Ne commit pas : a la charge de l'appelant (même transaction que la mise à jour de l'étape).
    """
    if nombre_jours <= 0:
        return
    solde = await obtenir_solde(db, utilisateur_id, type_conge_id, exercice, verrouiller=True)
    if solde is None:
        # Ne devrait pas arriver si le controle a ete fait avant ; on evite de planter une
        # decision deja actee plutot que de lever une erreur.
        return
    solde.solde_jours = float(solde.solde_jours) - nombre_jours
    solde.jours_pris = float(solde.jours_pris) + nombre_jours
    _ecrire_mouvement(
        db, utilisateur_id, type_conge_id, exercice, demande_id, -nombre_jours, MotifMouvementConges.RESERVATION
    )
    await db.flush()
