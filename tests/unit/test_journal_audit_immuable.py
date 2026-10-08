"""
Inalterabilite du journal d'audit (CDC fonctionnel 2.4 ; CDC technique 14.3) : ajout seul.
Chaque niveau de defense est teste separement, contournements compris.
"""
import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError

from app.models.journal_audit import JournalAudit, JournalImmuable
from app.services import audit


async def _entree(db):
    entree = await audit.consigner(db, action="demande_soumise", acteur_id=None, cible_type="demande", cible_id=None, details={"a": 1})
    await db.commit()
    return entree


async def test_l_ajout_reste_possible(db_session):
    entree = await _entree(db_session)
    assert entree.id is not None


async def test_niveau_orm_la_modification_d_une_entree_est_refusee(db_session):
    entree = await _entree(db_session)
    entree.action = "falsifiee"
    with pytest.raises(JournalImmuable):
        await db_session.commit()
    await db_session.rollback()


async def test_niveau_orm_la_suppression_d_une_entree_est_refusee(db_session):
    entree = await _entree(db_session)
    await db_session.delete(entree)
    with pytest.raises(JournalImmuable):
        await db_session.commit()
    await db_session.rollback()


async def test_niveau_base_un_update_de_masse_contourne_l_orm_mais_pas_le_declencheur(db_session):
    await _entree(db_session)
    with pytest.raises(DBAPIError, match="ajout seul"):
        await db_session.execute(update(JournalAudit).values(action="falsifiee"))
    await db_session.rollback()


async def test_niveau_base_un_delete_de_masse_est_refuse(db_session):
    await _entree(db_session)
    with pytest.raises(DBAPIError, match="ajout seul"):
        await db_session.execute(delete(JournalAudit))
    await db_session.rollback()


async def test_niveau_base_le_sql_brut_est_refuse_lui_aussi(db_session):
    await _entree(db_session)
    with pytest.raises(DBAPIError, match="ajout seul"):
        await db_session.execute(text("UPDATE journal_audit SET details = '{}'"))
    await db_session.rollback()
    with pytest.raises(DBAPIError, match="ajout seul"):
        await db_session.execute(text("DELETE FROM journal_audit"))
    await db_session.rollback()


async def test_le_contenu_est_intact_apres_les_tentatives(db_session):
    from sqlalchemy import select

    await _entree(db_session)
    for requete in (update(JournalAudit).values(action="x"), delete(JournalAudit)):
        with pytest.raises(DBAPIError):
            await db_session.execute(requete)
        await db_session.rollback()

    lignes = (await db_session.execute(select(JournalAudit))).scalars().all()
    assert [(l.action, l.details) for l in lignes] == [("demande_soumise", {"a": 1})]
