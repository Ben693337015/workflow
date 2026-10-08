"""
Gestion des jours fériés (écart identifié lors de la revue comparative avec
des plateformes de référence — le calcul de durée des congés ne tenait pas
compte des jours fériés).
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jour_ferie import JourFerie


def _jours_de_la_periode(date_debut: date, date_fin: date) -> list[date]:
    nombre_jours = (date_fin - date_debut).days + 1
    return [date_debut + timedelta(days=i) for i in range(nombre_jours)]


async def jours_feries_dans_periode(db: AsyncSession, date_debut: date, date_fin: date) -> int:
    """
    Compte le nombre de jours de [date_debut, date_fin] qui sont fériés.

    Un jour férié non récurrent doit tomber exactement dans la période ; un
    jour férié récurrent est comparé uniquement sur (mois, jour), quelle que
    soit l'année à laquelle il a été initialement enregistré.
    """
    resultat = await db.execute(select(JourFerie))
    jours_feries = resultat.scalars().all()

    jours_recurrents = {(jf.date.month, jf.date.day) for jf in jours_feries if jf.recurrent}
    jours_fixes = {jf.date for jf in jours_feries if not jf.recurrent}

    compteur = 0
    for jour in _jours_de_la_periode(date_debut, date_fin):
        if jour in jours_fixes or (jour.month, jour.day) in jours_recurrents:
            compteur += 1
    return compteur


async def compter_jours_deductibles(
    db: AsyncSession, date_debut: date, date_fin: date, exclure_weekends: bool = False
) -> int:
    """
    Nombre de jours a imputer sur le solde pour la periode [date_debut, date_fin] (bornes incluses).

    - `exclure_weekends=False` : jours calendaires, seuls les jours feries sont retranches
      (regle historique, conservee tant que la DRH n'en a pas valide une autre - R20) ;
    - `exclure_weekends=True` : seuls les jours du lundi au vendredi sont comptes. Un jour
      ferie qui tombe un week-end n'est pas retranche deux fois.
    """
    resultat = await db.execute(select(JourFerie))
    jours_feries = resultat.scalars().all()
    jours_recurrents = {(jf.date.month, jf.date.day) for jf in jours_feries if jf.recurrent}
    jours_fixes = {jf.date for jf in jours_feries if not jf.recurrent}

    compteur = 0
    for jour in _jours_de_la_periode(date_debut, date_fin):
        if exclure_weekends and jour.weekday() >= 5:
            continue
        est_ferie = jour in jours_fixes or (jour.month, jour.day) in jours_recurrents
        if not est_ferie:
            compteur += 1
    return compteur
