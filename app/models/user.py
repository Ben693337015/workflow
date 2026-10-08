"""Entite Utilisateurs (section 4 du CDC technique)."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import RoleUtilisateur


class Utilisateur(Base):
    __tablename__ = "utilisateurs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Ecart corrige (revue du 15/09) : nullable desormais - un compte cree
    # par le DRH (invitation, section 5) n'a pas encore de mot de passe tant
    # que l'employe n'a pas suivi son lien d'invitation (JetonCompte). Un
    # compte avec mot_de_passe_hash=None est traite comme "non active" a la
    # connexion (app/routers/auth.py).
    mot_de_passe_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nom_complet: Mapped[str] = mapped_column(String(255), nullable=False)
    service: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[RoleUtilisateur] = mapped_column(
        Enum(RoleUtilisateur, name="role_utilisateur", native_enum=False), nullable=False
    )
    # Cle etrangere auto-referente (R24) : un manager doit etre un compte existant. Les routes
    # validaient deja l'existence ; la base l'impose desormais aussi.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("utilisateurs.id"), nullable=True)
    actif: Mapped[bool] = mapped_column(default=True)
    # Limitation des connexions echouees (CDC 5 et 4.2.1, R9) : compteur remis a zero a chaque connexion
    # reussie et a chaque verrouillage ; `verrouille_jusqua` bloque toute tentative jusqu'a cette date.
    tentatives_echouees: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    verrouille_jusqua: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dernier_login_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    @property
    def compte_active(self) -> bool:
        """
        Ecart identifié (revue du 16/09) : exposé pour permettre à
        l'interface d'administration de proposer "Renvoyer l'invitation"
        uniquement sur les comptes qui en ont réellement besoin (jamais
        connectés), et "Réinitialiser le mot de passe" sur les autres.
        """
        return self.mot_de_passe_hash is not None
