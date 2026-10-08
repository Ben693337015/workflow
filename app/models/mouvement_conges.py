"""
Journal des mouvements du solde de conges (CDC technique 4.2.7 et 11.1).

`soldes_conges.solde_jours` (solde DISPONIBLE) n'est que la somme materialisee de
ces mouvements : credit positif, reservation negative, liberation positive. Un
solde errone reste ainsi toujours reconstituable et explicable a posteriori.

Precision de conception : le passage d'une reservation a une consommation
(approbation) ne change pas le solde disponible, il deplace seulement des jours de
`jours_reserves` vers `jours_pris`. Il n'y a donc pas de mouvement a ce moment-la.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import MotifMouvementConges


class MouvementConges(Base):
    __tablename__ = "mouvements_conges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id"), nullable=False, index=True
    )
    # Le solde est tenu par type de conge et par exercice : le mouvement porte la meme cle.
    type_conge_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("types_conge.id"), nullable=False)
    exercice: Mapped[int] = mapped_column(nullable=False)
    # Nul pour un mouvement qui ne se rattache a aucune demande (solde initial, ajustement RH).
    demande_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("demandes.id"), nullable=True, index=True
    )
    delta: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False)
    motif: Mapped[MotifMouvementConges] = mapped_column(
        Enum(MotifMouvementConges, name="motif_mouvement_conges", native_enum=False), nullable=False
    )
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
