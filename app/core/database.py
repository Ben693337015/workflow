"""
Configuration de la base de donnees (section 3.3 / 4 du CDC technique).

PostgreSQL, accede en mode asynchrone via SQLAlchemy, versionne par Alembic.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """Classe de base declarative pour tous les modeles SQLAlchemy."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependance FastAPI fournissant une session de base de donnees par requete."""
    async with AsyncSessionLocal() as session:
        yield session
