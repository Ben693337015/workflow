"""
Entité Jours fériés (écart identifié : le calcul de durée des congés ne
tenait pas compte des jours fériés, contrairement aux plateformes de
référence analysées).

Simplification assumée : un jour férié est un jour calendaire unique (pas
une plage). Une fermeture d'entreprise sur plusieurs jours se modélise par
plusieurs lignes plutôt que par un intervalle - plus simple à faire
correspondre avec la règle de récurrence annuelle.
"""
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JourFerie(Base):
    __tablename__ = "jours_feries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    # Si True, le jour est férié chaque année à la même date (mois/jour),
    # quelle que soit l'année stockée ici (ex. 1er mai).
    recurrent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
