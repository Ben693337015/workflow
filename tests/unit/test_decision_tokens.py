"""
Tests unitaires - jetons de décision par e-mail (section 9).

Réécrits intégralement (revue du 15/09) : le mécanisme sous-jacent est
passé d'`itsdangerous` (signature locale, sans base) à un jeton opaque
vérifié/consommé contre la table `jetons_decision` (section 9.2-9.3) -
ces tests s'appuient donc sur `db_session` comme les autres services qui
touchent la base.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.jeton_decision import JetonDecision
from app.services import decision_tokens

pytestmark = pytest.mark.asyncio


async def test_jeton_valide_est_verifie_avec_les_bonnes_donnees(db_session):
    etape_id = uuid.uuid4()
    approbateur_id = uuid.uuid4()

    jeton = await decision_tokens.generer_jeton_decision(db_session, etape_id, "approuver", approbateur_id)
    ligne = await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton)

    assert ligne.etape_workflow_id == etape_id
    assert ligne.action_autorisee == "approuver"
    assert ligne.approbateur_attendu_id == approbateur_id
    assert ligne.utilise_a is None  # verification seule : pas encore consomme (§9.3, etape 13)


async def test_jeton_en_clair_nest_jamais_persiste(db_session):
    """Exigence explicite de la section 9.3 : seule l'empreinte est en base."""
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.uuid4(), "approuver", uuid.uuid4())

    ligne = (await db_session.execute(__import__("sqlalchemy").select(JetonDecision))).scalars().first()

    assert ligne.token_hash != jeton
    assert jeton not in ligne.token_hash
    assert len(ligne.token_hash) == 64  # empreinte SHA-256 hexadecimale


async def test_jeton_inconnu_est_rejete(db_session):
    with pytest.raises(ValueError, match="invalide ou inconnu"):
        await decision_tokens.verifier_et_consommer_jeton_decision(db_session, "ceci-nest-pas-un-jeton-emis")


async def test_jeton_expire_est_rejete(db_session):
    jeton = await decision_tokens.generer_jeton_decision(
        db_session, uuid.uuid4(), "refuser", uuid.uuid4(), duree_de_vie_heures=-1
    )

    with pytest.raises(ValueError, match="expiré"):
        await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton)


async def test_jeton_deja_consomme_est_rejete(db_session):
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.uuid4(), "approuver", uuid.uuid4())

    ligne = await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton)
    decision_tokens.consommer_jeton_decision(ligne)
    await db_session.commit()

    with pytest.raises(ValueError, match="déjà utilisé"):
        await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton)


async def test_jeton_revoque_est_rejete(db_session):
    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.uuid4(), "approuver", uuid.uuid4())
    ligne = (await db_session.execute(__import__("sqlalchemy").select(JetonDecision))).scalars().first()
    ligne.revoque = True
    await db_session.commit()

    with pytest.raises(ValueError, match="révoqué"):
        await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton)


async def test_deux_actions_pour_la_meme_etape_donnent_des_jetons_differents(db_session):
    etape_id = uuid.uuid4()
    approbateur_id = uuid.uuid4()

    jeton_approuver = await decision_tokens.generer_jeton_decision(db_session, etape_id, "approuver", approbateur_id)
    jeton_refuser = await decision_tokens.generer_jeton_decision(db_session, etape_id, "refuser", approbateur_id)

    assert jeton_approuver != jeton_refuser

    ligne_approuver = await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton_approuver)
    ligne_refuser = await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton_refuser)
    assert ligne_approuver.action_autorisee == "approuver"
    assert ligne_refuser.action_autorisee == "refuser"


async def test_consommer_un_jeton_ne_consomme_pas_lautre_jeton_de_la_meme_etape(db_session):
    """
    Vérifie l'écart corrigé (revue du 15/09) : consommer le jeton "approuver"
    ne doit pas invalider le jeton "refuser" de la même étape au niveau du
    jeton lui-même (c'est `etape.statut`, côté routeur, qui empêche l'usage
    de l'un après l'autre - voir tests d'intégration).
    """
    etape_id = uuid.uuid4()
    approbateur_id = uuid.uuid4()
    jeton_approuver = await decision_tokens.generer_jeton_decision(db_session, etape_id, "approuver", approbateur_id)
    jeton_refuser = await decision_tokens.generer_jeton_decision(db_session, etape_id, "refuser", approbateur_id)

    ligne_approuver = await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton_approuver)
    decision_tokens.consommer_jeton_decision(ligne_approuver)
    await db_session.commit()

    ligne_refuser = await decision_tokens.verifier_et_consommer_jeton_decision(db_session, jeton_refuser)
    assert ligne_refuser.utilise_a is None
