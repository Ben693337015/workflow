"""Tests unitaires - jours fériés (écart identifié suite à la revue comparative)."""
from datetime import date

from app.models.jour_ferie import JourFerie
from app.services.calendrier import jours_feries_dans_periode


async def test_aucun_jour_ferie_dans_la_periode(db_session):
    compte = await jours_feries_dans_periode(db_session, date(2026, 6, 1), date(2026, 6, 5))
    assert compte == 0


async def test_deux_jours_feries_distincts_dans_la_periode(db_session):
    db_session.add(JourFerie(nom="Jour A", date=date(2026, 6, 2), recurrent=False))
    db_session.add(JourFerie(nom="Jour B", date=date(2026, 6, 4), recurrent=False))
    await db_session.commit()

    compte = await jours_feries_dans_periode(db_session, date(2026, 6, 1), date(2026, 6, 5))
    assert compte == 2


async def test_jour_ferie_hors_periode_nest_pas_compte(db_session):
    db_session.add(JourFerie(nom="Hors période", date=date(2026, 7, 14), recurrent=False))
    await db_session.commit()

    compte = await jours_feries_dans_periode(db_session, date(2026, 6, 1), date(2026, 6, 5))
    assert compte == 0


async def test_jour_ferie_recurrent_compte_independamment_de_lannee_stockee(db_session):
    db_session.add(JourFerie(nom="Noël", date=date(2020, 12, 25), recurrent=True))
    await db_session.commit()

    compte = await jours_feries_dans_periode(db_session, date(2026, 12, 24), date(2026, 12, 26))
    assert compte == 1


async def test_jour_ferie_non_recurrent_dune_autre_annee_nest_pas_compte(db_session):
    db_session.add(JourFerie(nom="Jour ponctuel 2020", date=date(2020, 12, 25), recurrent=False))
    await db_session.commit()

    compte = await jours_feries_dans_periode(db_session, date(2026, 12, 24), date(2026, 12, 26))
    assert compte == 0
