"""Correction R9 : limitation des connexions echouees (CDC section 5) et colonne `tentatives_echouees` (4.2.1)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import RoleUtilisateur
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur

BON = "MonMotDePasse123!"


@pytest.fixture(autouse=True)
def _reglages(monkeypatch):
    monkeypatch.setattr(get_settings(), "connexion_max_tentatives", 3)
    monkeypatch.setattr(get_settings(), "connexion_duree_verrouillage_minutes", 15)


async def _utilisateur(db_session, email="a@example.com", avec_mot_de_passe=True):
    u = Utilisateur(
        email=email, mot_de_passe_hash=hash_password(BON) if avec_mot_de_passe else None,
        nom_complet="A", service="S", role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def _essayer(client, mot_de_passe, email="a@example.com"):
    return await client.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": mot_de_passe})


async def _recharger(db_session, utilisateur):
    resultat = await db_session.execute(
        select(Utilisateur).where(Utilisateur.id == utilisateur.id).execution_options(populate_existing=True)
    )
    return resultat.scalar_one()


async def _actions(db_session):
    return [e.action for e in (await db_session.execute(select(JournalAudit).order_by(JournalAudit.horodate_le))).scalars()]


async def test_un_echec_incremente_le_compteur_et_reste_une_401(client, db_session):
    u = await _utilisateur(db_session)
    reponse = await _essayer(client, "mauvais")
    assert reponse.status_code == 401
    assert (await _recharger(db_session, u)).tentatives_echouees == 1


async def test_le_seuil_verrouille_le_compte(client, db_session):
    u = await _utilisateur(db_session)
    for _ in range(3):
        assert (await _essayer(client, "mauvais")).status_code == 401

    u = await _recharger(db_session, u)
    assert u.verrouille_jusqua is not None
    assert u.tentatives_echouees == 0  # remis a zero au verrouillage : le compteur repart apres l'expiration
    assert "compte_verrouille" in await _actions(db_session)


async def test_compte_verrouille_refuse_meme_le_bon_mot_de_passe(client, db_session):
    await _utilisateur(db_session)
    for _ in range(3):
        await _essayer(client, "mauvais")

    reponse = await _essayer(client, BON)

    assert reponse.status_code == 429
    assert int(reponse.headers["Retry-After"]) > 0
    assert "tentatives" in reponse.json()["detail"].lower()


async def test_le_verrouillage_expire(client, db_session):
    u = await _utilisateur(db_session)
    for _ in range(3):
        await _essayer(client, "mauvais")
    u = await _recharger(db_session, u)
    u.verrouille_jusqua = datetime.now(UTC) - timedelta(seconds=1)  # echeance depassee
    await db_session.commit()

    reponse = await _essayer(client, BON)

    assert reponse.status_code == 200


async def test_une_connexion_reussie_remet_le_compteur_a_zero(client, db_session):
    u = await _utilisateur(db_session)
    await _essayer(client, "mauvais")
    await _essayer(client, "mauvais")
    assert (await _recharger(db_session, u)).tentatives_echouees == 2

    assert (await _essayer(client, BON)).status_code == 200

    u = await _recharger(db_session, u)
    assert u.tentatives_echouees == 0
    assert u.dernier_login_le is not None
    assert "connexion_reussie" in await _actions(db_session)


async def test_les_echecs_espaces_par_un_succes_ne_verrouillent_jamais(client, db_session):
    u = await _utilisateur(db_session)
    for _ in range(5):
        await _essayer(client, "mauvais")
        await _essayer(client, "mauvais")
        assert (await _essayer(client, BON)).status_code == 200  # jamais 3 echecs consecutifs
    assert (await _recharger(db_session, u)).verrouille_jusqua is None


async def test_un_email_inconnu_ne_cree_rien_et_repond_401(client, db_session):
    reponse = await _essayer(client, "mauvais", email="inconnu@example.com")
    assert reponse.status_code == 401
    assert await _actions(db_session) == []


async def test_un_compte_jamais_active_ne_compte_pas_d_echecs(client, db_session):
    u = await _utilisateur(db_session, avec_mot_de_passe=False)
    for _ in range(5):
        assert (await _essayer(client, "mauvais")).status_code == 401
    u = await _recharger(db_session, u)
    assert u.tentatives_echouees == 0 and u.verrouille_jusqua is None


async def test_le_compteur_est_persiste_malgre_la_401(client, db_session):
    """Regression : lever une 401 sans commit annulerait le compteur (la session est abandonnee)."""
    u = await _utilisateur(db_session)
    await _essayer(client, "mauvais")
    await db_session.rollback()  # comme la fin de requete en production
    assert (await _recharger(db_session, u)).tentatives_echouees == 1
    assert "connexion_echouee" in await _actions(db_session)


async def test_la_reinitialisation_du_mot_de_passe_leve_le_verrou(client, db_session):
    from app.models.enums import TypeJetonCompte
    from app.services import jetons_compte

    u = await _utilisateur(db_session)
    for _ in range(3):
        await _essayer(client, "mauvais")
    assert (await _essayer(client, BON)).status_code == 429
    jeton = await jetons_compte.generer_jeton_compte(db_session, u.id, TypeJetonCompte.REINITIALISATION)
    await db_session.commit()

    reinit = await client.post(
        "/api/v1/auth/definir-mot-de-passe", json={"jeton": jeton, "mot_de_passe": "NouveauMotDePasse456!"}
    )

    assert reinit.status_code == 200
    assert (await _essayer(client, "NouveauMotDePasse456!")).status_code == 200
