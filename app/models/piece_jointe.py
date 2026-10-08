"""Entite Pieces jointes : reference vers le stockage de fichiers (section 4 / 3.3)."""
import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CategoriePiece(str, enum.Enum):
    """
    Nature d'une piece jointe. Avant cette colonne, "le contrat d'un achat" etait
    deduit de "la piece la plus recente sans message" : ambigu des qu'une autre
    piece existait. La categorie est desormais explicite.
    """

    CONTRAT = "contrat"  # achats : fichier du contrat, depose a la soumission (CDC 3)
    RECU = "recu"  # notes de frais : reçu fiscal (CDC 3)
    JUSTIFICATIF = "justificatif"  # conges : justificatif d'absence (CDC 3)
    COMPLEMENT = "complement"  # achats : documents supplementaires (CDC 2.1 : "un ou plusieurs documents")
    DISCUSSION = "discussion"  # piece deposee dans l'espace de discussion (CDC 4.5)


class PieceJointe(Base):
    __tablename__ = "pieces_jointes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    demande_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("demandes.id"), nullable=False
    )
    nom_original: Mapped[str] = mapped_column(String(255), nullable=False)
    cle_stockage: Mapped[str] = mapped_column(String(512), nullable=False)  # cle objet NubiS3
    # Renseigne uniquement pour une piece deposee dans l'espace de discussion
    # (ecart n°5, section 4.5 : "le depot de pieces complementaires doit
    # s'effectuer au sein de cet espace"). NULL pour le contrat d'un achat.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages_clarification.id"), nullable=True
    )
    categorie: Mapped[str] = mapped_column(String(30), nullable=False, default=CategoriePiece.COMPLEMENT.value)
    deposee_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    demande: Mapped["Demande"] = relationship(back_populates="pieces_jointes")
