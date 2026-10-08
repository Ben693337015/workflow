"""Entite Types de demande : definition des trois formulaires (section 4 / 6)."""
import uuid

from sqlalchemy import Enum, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import TypeProcessus


class TypeDemande(Base):
    __tablename__ = "types_demande"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    processus: Mapped[TypeProcessus] = mapped_column(
        Enum(TypeProcessus, name="type_processus", native_enum=False), unique=True, nullable=False
    )
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    # Definition des champs et validations du formulaire (section 6), au format JSON
    # pour rester configurable sans migration a chaque ajustement mineur.
    schema_champs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
