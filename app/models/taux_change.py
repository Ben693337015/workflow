"""
Taux de change (decision du 28/09 : "plusieurs devises avec conversion").

Un taux exprime combien d'unites de la devise de REFERENCE (Settings.devise_reference) valent une
unite de `devise` : 1 USD = 0,92 EUR s'enregistre `taux = 0.92`. Chaque taux a une date d'effet ;
celui applique a une depense est le plus recent dont la date d'effet n'est pas posterieure a la
date de la depense. Le taux retenu est ensuite FIGE sur la demande (voir app/services/devises.py) :
modifier un taux plus tard ne change jamais un engagement deja pris.
"""
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TauxChange(Base):
    __tablename__ = "taux_change"
    __table_args__ = (UniqueConstraint("devise", "date_effet", name="uq_taux_change_devise_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    devise: Mapped[str] = mapped_column(String(3), nullable=False)
    taux: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    date_effet: Mapped[date] = mapped_column(Date, nullable=False)
    defini_par_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("utilisateurs.id"), nullable=True)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
