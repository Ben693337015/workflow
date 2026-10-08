"""Entite Demandes : une ligne par soumission (section 4)."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import StatutDemande, TypeProcessus


class Demande(Base):
    __tablename__ = "demandes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    processus: Mapped[TypeProcessus] = mapped_column(
        Enum(TypeProcessus, name="type_processus", native_enum=False), nullable=False
    )
    demandeur_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id"), nullable=False
    )
    # Ecart identifié : distingue le titulaire de la demande (demandeur_id) de
    # la personne qui l'a effectivement soumise (initiee_par_id). Identiques
    # dans le cas normal ; différents pour une régularisation faite par un
    # manager/DRH au nom d'un employé (absence constatée après coup).
    initiee_par_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id"), nullable=False
    )
    # Donnees saisies specifiques au processus (dates de conge, montant, tiers, etc.)
    # JSONB sur PostgreSQL (CDC 4.1, R24) : comparable et indexable ; JSON generique ailleurs (tests SQLite).
    donnees: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    statut_global: Mapped[StatutDemande] = mapped_column(
        Enum(StatutDemande, name="statut_demande", native_enum=False),
        nullable=False,
        default=StatutDemande.EN_COURS,
    )
    # Python-side (pas server_default) : garantit une résolution microseconde
    # et un ordre chronologique fiable entre créations rapprochées, ce qu'un
    # now() côté serveur (résolution seconde sous SQLite, figé par
    # transaction sous PostgreSQL) ne garantit pas.
    creee_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    etapes: Mapped[list["EtapeWorkflow"]] = relationship(back_populates="demande")
    pieces_jointes: Mapped[list["PieceJointe"]] = relationship(back_populates="demande")
