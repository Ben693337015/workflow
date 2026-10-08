"""
Fixtures partagees.

Les tests tournent sur une base SQLite en memoire (aiosqlite) plutot que sur
PostgreSQL, pour rester rapides et independants de l'infrastructure NubieCloud.
Les types specifiques a PostgreSQL (UUID, ARRAY, ENUM natif) devront etre
adaptes ou mockes au moment de l'implementation reelle des modeles concernes -
voir la note dans tests/unit/test_models.py.
"""
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _cle_resend_de_test(monkeypatch):
    """
    La suite ne doit pas dependre du `.env` de la machine : `.env.example` laisse RESEND_API_KEY vide (en
    developpement, les e-mails sont alors ecrits dans les logs au lieu d'etre envoyes), ce qui court-circuiterait
    les tests du vrai chemin Resend. Une cle factice est donc imposee ; un test qui veut le cas « cle vide » la
    remplace lui-meme.
    """
    import resend

    from app.services import email_service

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(resend, "api_key", "re_test_key")


@pytest.fixture(autouse=True)
def _stockage_fichiers_isole(tmp_path, monkeypatch):
    """
    Les fichiers deposes pendant les tests (contrats, pieces de discussion,
    signatures) vont dans un dossier temporaire propre a chaque test. Sans
    cela, la valeur par defaut (/var/lib/workflows/pieces-jointes) etait
    utilisee : les tests echouaient sans droits d'ecriture sur ce chemin et
    laissaient des fichiers parasites derriere eux (355 constates).
    """
    from app.services import stockage_fichiers

    monkeypatch.setattr(stockage_fichiers.settings, "stockage_fichiers_dossier", str(tmp_path / "pieces-jointes"))


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncClient:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
