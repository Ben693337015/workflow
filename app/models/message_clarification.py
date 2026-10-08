"""
Entite Messages de clarification (ecart n°5, section 4.5 du CDC fonctionnel).

Espace de discussion parallele au flux de validation, ouvert par
l'approbateur en cours pour suspendre temporairement une decision et
demander des precisions - plutot que la seule alternative du flux
standard (refuser purement et simplement, obligeant le demandeur a tout
ressaisir). Table generique (une Demande, quel que soit son processus)
plutot que dupliquee par processus - coherent avec le reste de
l'infrastructure (Demande, EtapeWorkflow, PieceJointe).
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column


from app.core.database import Base


class MessageClarification(Base):
    __tablename__ = "messages_clarification"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    demande_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("demandes.id"), nullable=False)
    auteur_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("utilisateurs.id"), nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
