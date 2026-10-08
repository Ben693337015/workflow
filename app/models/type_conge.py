"""
Entité Types de congé (écart identifié lors de la revue comparative — un
type de congé structuré était implicite dans la décision déjà confirmée
"taux d'acquisition paramétrable", mais n'existait pas encore comme entité).

Chaque type de congé (congé payé, maladie, sans solde...) a son propre taux
d'acquisition et son propre solde par utilisateur (voir SoldeConges).
"""
import uuid

from sqlalchemy import Boolean, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TypeConge(Base):
    __tablename__ = "types_conge"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    # Jours acquis par mois travaillé ; paramétrable par type (décision déjà
    # confirmée : "taux d'acquisition non figé, doit suivre les normes internes").
    taux_acquisition_jours_mois: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
