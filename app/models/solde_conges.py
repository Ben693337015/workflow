"""
Entité Soldes de congés : extension native écart n2, verrou RH (section 4 / 11).

Étendue (écart identifié) : le solde est désormais détaillé par type de
congé (congé payé, maladie...) et distingue jours acquis / pris / restants,
plutôt qu'un simple nombre agrégé - pour la traçabilité et l'affichage.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SoldeConges(Base):
    __tablename__ = "soldes_conges"
    __table_args__ = (
        UniqueConstraint("utilisateur_id", "type_conge_id", "exercice", name="uq_solde_utilisateur_type_exercice"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("utilisateurs.id"), nullable=False)
    type_conge_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("types_conge.id"), nullable=False)
    exercice: Mapped[int] = mapped_column(nullable=False)

    # Report de solde illimité (décision confirmée) ; jours entiers uniquement.
    jours_acquis: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False, default=0)
    jours_pris: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False, default=0)
    # Jours reserves par des demandes encore en cours (R17) : retires du solde disponible
    # des la soumission, pour que deux demandes rapprochees ne puissent pas depasser le
    # solde reel. Passent en `jours_pris` a l'approbation, ou reviennent au solde en cas
    # de refus, d'annulation ou de modification.
    jours_reserves: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False, default=0, server_default="0")
    # Solde réellement disponible = jours_acquis - jours_pris - jours_reserves ; stocké
    # (et non recalculé à la volée) pour que le verrou RH reste une simple lecture. Il
    # est egal a la somme des mouvements de `mouvements_conges`.
    solde_jours: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False, default=0)

    mis_a_jour_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
