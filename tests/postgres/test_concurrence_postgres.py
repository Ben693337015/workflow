"""
Tests de CONCURRENCE sur un vrai PostgreSQL (R17, R21).

SQLite ne peut pas les prouver : il serialise tout par construction et ignore `SELECT ... FOR UPDATE`.
Ces tests lancent de vraies requetes simultanees, chacune sur sa propre connexion.

Executes seulement si WORKFLOWS_TEST_POSTGRES_URL est defini (base JETABLE : toutes les tables sont
supprimees puis recreees). Exemple :
    WORKFLOWS_TEST_POSTGRES_URL=postgresql+asyncpg://user:pwd@localhost:5432/wf_conc pytest tests/postgres
"""
import asyncio
import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import Base, get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.demande import Demande
from app.models.enums import MotifMouvementConges, RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.mouvement_conges import MouvementConges
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.services import numerotation_bc

URL = os.environ.get("WORKFLOWS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="WORKFLOWS_TEST_POSTGRES_URL non defini")


@pytest_asyncio.fixture
async def fabrique():
    moteur = create_async_engine(URL, poolclass=NullPool)  # une vraie connexion par session
    async with moteur.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(moteur, expire_on_commit=False)
    await moteur.dispose()


@pytest.fixture(autouse=True)
def _pas_d_email(monkeypatch):
    monkeypatch.setattr("app.routers.conges.email_service.envoyer_email", AsyncMock())


async def _employe_avec_solde(fabrique, solde_jours):
    async with fabrique() as s:
        manager = Utilisateur(email="m@x.fr", mot_de_passe_hash="h", nom_complet="M", service="S", role=RoleUtilisateur.MANAGER)
        s.add(manager)
        await s.flush()
        employe = Utilisateur(
            email="e@x.fr", mot_de_passe_hash="h", nom_complet="E", service="S",
            role=RoleUtilisateur.EMPLOYE, manager_id=manager.id,
        )
        type_conge = TypeConge(code="cp", nom="CP", taux_acquisition_jours_mois=2.5)
        s.add_all([employe, type_conge])
        await s.flush()
        s.add(SoldeConges(
            utilisateur_id=employe.id, type_conge_id=type_conge.id, exercice=2026,
            jours_acquis=solde_jours, jours_pris=0, jours_reserves=0, solde_jours=solde_jours,
        ))
        s.add(MouvementConges(
            utilisateur_id=employe.id, type_conge_id=type_conge.id, exercice=2026, demande_id=None,
            delta=solde_jours, motif=MotifMouvementConges.SOLDE_INITIAL,
        ))
        await s.commit()
        return employe, type_conge


async def _soumissions_simultanees(fabrique, employe, type_conge, nombre, debut, fin):
    async def _get_db():
        async with fabrique() as session:  # une session NEUVE par requete, comme en production
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            corps = {"type_conge_id": str(type_conge.id), "date_debut": debut, "date_fin": fin}
            return await asyncio.gather(*[client.post("/api/v1/conges/", json=corps) for _ in range(nombre)])
    finally:
        app.dependency_overrides.clear()


async def test_deux_soumissions_simultanees_ne_depassent_pas_le_solde(fabrique):
    """5 jours de solde, deux demandes simultanees de 3 jours : une seule doit passer."""
    employe, type_conge = await _employe_avec_solde(fabrique, 5)

    reponses = await _soumissions_simultanees(fabrique, employe, type_conge, 2, "2026-06-01", "2026-06-03")

    codes = sorted(r.status_code for r in reponses)
    assert codes == [201, 422], codes
    async with fabrique() as s:
        solde = (await s.execute(select(SoldeConges))).scalar_one()
        assert float(solde.solde_jours) == 2
        assert float(solde.jours_reserves) == 3
        assert (await s.execute(select(func.count()).select_from(Demande))).scalar_one() == 1


async def test_dix_soumissions_simultanees_acceptent_exactement_ce_que_le_solde_permet(fabrique):
    """10 jours de solde, 10 demandes de 3 jours en meme temps : exactement 3 passent (9 jours)."""
    employe, type_conge = await _employe_avec_solde(fabrique, 10)

    reponses = await _soumissions_simultanees(fabrique, employe, type_conge, 10, "2026-06-01", "2026-06-03")

    acceptees = [r for r in reponses if r.status_code == 201]
    refusees = [r for r in reponses if r.status_code == 422]
    assert len(acceptees) == 3 and len(refusees) == 7, sorted(r.status_code for r in reponses)
    async with fabrique() as s:
        solde = (await s.execute(select(SoldeConges))).scalar_one()
        assert float(solde.solde_jours) == 1
        assert float(solde.jours_reserves) == 9
        total = (await s.execute(select(func.sum(MouvementConges.delta)))).scalar_one()
        assert float(total) == float(solde.solde_jours)  # le journal explique exactement le solde


async def test_numeros_de_bon_de_commande_uniques_sous_concurrence(fabrique):
    """12 attributions simultanees sur un exercice NEUF (course sur la creation du compteur comprise)."""
    async with fabrique() as s:
        u = Utilisateur(email="a@x.fr", mot_de_passe_hash="h", nom_complet="A", service="S", role=RoleUtilisateur.EMPLOYE)
        s.add(u)
        await s.flush()
        ids = []
        for _ in range(12):
            d = Demande(processus=TypeProcessus.ACHATS, demandeur_id=u.id, initiee_par_id=u.id,
                        donnees={}, statut_global=StatutDemande.TERMINEE)
            s.add(d)
            await s.flush()
            ids.append(d.id)
        await s.commit()

    async def _attribuer(demande_id):
        async with fabrique() as s:  # transaction propre a chaque attribution
            demande = await s.get(Demande, demande_id)
            numero = await numerotation_bc.attribuer_numero(s, demande, 2026)
            await s.commit()
            return numero

    numeros = await asyncio.gather(*[_attribuer(i) for i in ids])

    assert len(set(numeros)) == 12, f"doublons : {sorted(numeros)}"
    assert sorted(numeros) == [f"BC-2026-{n:04d}" for n in range(1, 13)]
