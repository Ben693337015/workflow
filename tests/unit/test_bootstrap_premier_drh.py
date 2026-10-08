"""
Tests du script de bootstrap du tout premier compte DRH.

Écart identifié (revue du 16/09) : sans ce script, aucun moyen de créer le
premier compte sur un déploiement neuf, puisque POST /api/v1/utilisateurs/
exige déjà d'être authentifié en tant que DRH.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from app.models.enums import RoleUtilisateur  # noqa: E402
from app.models.user import Utilisateur  # noqa: E402

import bootstrap_premier_drh  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_cree_le_premier_drh_sans_mot_de_passe(db_session, monkeypatch):
    # AsyncSessionLocal() est normalement un context manager (async with) ;
    # db_session (fixture) en est déjà un via son propre cycle de vie -
    # on emballe donc dans un faux context manager transparent.
    class _FauxContexte:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(bootstrap_premier_drh, "AsyncSessionLocal", lambda: _FauxContexte())

    async def _echoue(*a, **kw):
        raise RuntimeError("Resend non configuré dans ce test")

    monkeypatch.setattr(bootstrap_premier_drh.email_service, "envoyer_email", _echoue)

    await bootstrap_premier_drh.bootstrap(
        email="premier.drh@test.tld", nom_complet="Premier DRH", service="RH", force=False
    )

    resultat = await db_session.execute(select(Utilisateur).where(Utilisateur.email == "premier.drh@test.tld"))
    drh = resultat.scalar_one()
    assert drh.role == RoleUtilisateur.DRH
    assert drh.mot_de_passe_hash is None  # jamais de mot de passe en clair, meme pour ce compte


async def test_refuse_de_creer_un_second_drh_sans_force(db_session, monkeypatch, capsys):
    class _FauxContexte:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(bootstrap_premier_drh, "AsyncSessionLocal", lambda: _FauxContexte())

    drh_existant = Utilisateur(
        email="deja.drh@test.tld", mot_de_passe_hash="peu importe",
        nom_complet="Déjà DRH", service="RH", role=RoleUtilisateur.DRH,
    )
    db_session.add(drh_existant)
    await db_session.commit()

    with pytest.raises(SystemExit) as exc_info:
        await bootstrap_premier_drh.bootstrap(
            email="second.drh@test.tld", nom_complet="Second DRH", service="RH", force=False
        )
    assert exc_info.value.code == 1

    resultat = await db_session.execute(select(Utilisateur).where(Utilisateur.email == "second.drh@test.tld"))
    assert resultat.scalar_one_or_none() is None  # rien cree


async def test_refuse_un_email_deja_utilise(db_session, monkeypatch):
    class _FauxContexte:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(bootstrap_premier_drh, "AsyncSessionLocal", lambda: _FauxContexte())

    existant = Utilisateur(
        email="occupe@test.tld", mot_de_passe_hash="peu importe",
        nom_complet="Quelqu'un", service="Support", role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(existant)
    await db_session.commit()

    with pytest.raises(SystemExit):
        await bootstrap_premier_drh.bootstrap(
            email="occupe@test.tld", nom_complet="Nouveau DRH", service="RH", force=False
        )
