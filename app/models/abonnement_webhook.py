"""Entite Abonnements webhook : extension d'integration native (section 4 / 10)."""
import uuid

from sqlalchemy import Enum, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import EvenementWebhook, TypeProcessus


class AbonnementWebhook(Base):
    __tablename__ = "abonnements_webhook"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    url_destination: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Stocke CHIFFRE (prefixe "fernet:", app/core/chiffrement.py, R22). Ne jamais ecrire un secret en
    # clair : passer par app.services.webhooks.creer_abonnement. Longueur : le chiffrement multiplie
    # la taille par ~1,8 (un secret de 100 caracteres devient ~235) ; colonne a 512 pour accepter des
    # secrets jusqu'a ~250 caracteres.
    secret_hmac: Mapped[str] = mapped_column(String(512), nullable=False)
    processus: Mapped[TypeProcessus] = mapped_column(
        Enum(TypeProcessus, name="type_processus", native_enum=False), nullable=False
    )
    evenements: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    actif: Mapped[bool] = mapped_column(default=True)
