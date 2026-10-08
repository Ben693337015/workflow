"""
Attribution du numero de bon de commande (correction R21).

Format conserve : `BC-<exercice>-<rang sur 4 chiffres>` (ex. BC-2026-0007).

Garanties :
- le compteur de l'exercice est verrouille (`SELECT ... FOR UPDATE`) pour la duree de la
  transaction de decision : deux validations simultanees sont serialisees par la base ;
- l'unicite (exercice, rang) et l'unicite du numero sont en plus imposees par contrainte ;
- un rang n'est jamais reutilise, meme si la demande est ensuite annulee ou supprimee.

Ne commit pas : a la charge de l'appelant, dans la meme transaction que la decision.
"""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bon_commande import BonCommande, CompteurBonCommande
from app.models.demande import Demande


def _formater(exercice: int, rang: int) -> str:
    return f"BC-{exercice}-{rang:04d}"


async def _compteur_verrouille(db: AsyncSession, exercice: int) -> CompteurBonCommande:
    """Retourne le compteur de l'exercice, cree au besoin, verrouille pour la transaction."""
    dialecte = db.get_bind().dialect.name
    insert = pg_insert if dialecte == "postgresql" else sqlite_insert
    # Creation idempotente : si deux transactions arrivent en meme temps sur un exercice neuf,
    # l'une insere, l'autre est ignoree, puis toutes deux se retrouvent sur le verrou de ligne.
    await db.execute(
        insert(CompteurBonCommande)
        .values(exercice=exercice, dernier_rang=0)
        .on_conflict_do_nothing(index_elements=["exercice"])
    )
    resultat = await db.execute(
        select(CompteurBonCommande)
        .where(CompteurBonCommande.exercice == exercice)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return resultat.scalar_one()


async def attribuer_numero(db: AsyncSession, demande: Demande, exercice: int) -> str:
    """Attribue le prochain numero a la demande. Idempotent : un second appel renvoie le meme."""
    existant = await db.execute(select(BonCommande).where(BonCommande.demande_id == demande.id))
    bon = existant.scalar_one_or_none()
    if bon is not None:
        return bon.numero_sequentiel

    compteur = await _compteur_verrouille(db, exercice)
    compteur.dernier_rang += 1
    numero = _formater(exercice, compteur.dernier_rang)
    db.add(
        BonCommande(
            demande_id=demande.id, exercice=exercice, rang=compteur.dernier_rang, numero_sequentiel=numero
        )
    )
    await db.flush()
    return numero
