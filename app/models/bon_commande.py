"""
Bons de commande et compteur de numerotation (CDC technique 4.2.12, correction R21).

Avant : le numero `BC-AAAA-XXXX` etait calcule en COMPTANT les achats deja termines de
l'annee. Deux validations simultanees lisaient le meme total et recevaient le meme numero.

Maintenant : un compteur par exercice, verrouille pendant la transaction de decision
(`SELECT ... FOR UPDATE`), et une contrainte d'unicite en base qui rend un doublon
impossible meme si le verrou etait contourne.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CompteurBonCommande(Base):
    """Dernier rang attribue pour un exercice (une ligne par annee)."""

    __tablename__ = "compteurs_bon_commande"

    exercice: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    dernier_rang: Mapped[int] = mapped_column(nullable=False, default=0)


class BonCommande(Base):
    __tablename__ = "bons_commande"
    __table_args__ = (UniqueConstraint("exercice", "rang", name="uq_bon_commande_exercice_rang"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Un seul bon de commande par demande d'achat (CDC 4.2.12).
    demande_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("demandes.id"), unique=True, nullable=False
    )
    exercice: Mapped[int] = mapped_column(nullable=False)
    rang: Mapped[int] = mapped_column(nullable=False)
    numero_sequentiel: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
