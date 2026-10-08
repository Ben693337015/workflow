"""Entite Enveloppes budgetaires : extension native ecart n3 (section 4 / 11)."""
import uuid

from sqlalchemy import Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EnveloppeBudgetaire(Base):
    __tablename__ = "enveloppes_budgetaires"
    __table_args__ = (UniqueConstraint("service", "exercice", name="uq_enveloppe_service_exercice"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service: Mapped[str] = mapped_column(String(120), nullable=False)
    exercice: Mapped[int] = mapped_column(nullable=False)
    budget_alloue: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    budget_consomme: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
