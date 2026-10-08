"""
Entite Jetons de decision (section 4.2.5) - modele retenu a l'issue du
benchmark de la section 9.2 (JWT et itsdangerous ecartes au profit d'un
jeton opaque dont seule l'empreinte SHA-256 est persistee).

Ecart identifie et corrige (revue du 15/09) : cette entite dediee n'existait
pas dans le code avant cette date - le jeton vivait en clair dans un simple
champ de EtapeWorkflow, exactement le design pre-V2.7 explicitement decrit
par le CDC comme deja depasse ("esquisse dans les versions anterieures de
ce document comme un simple champ de la table des etapes de workflow").
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JetonDecision(Base):
    __tablename__ = "jetons_decision"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    etape_workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("etapes_workflow.id"), nullable=False
    )
    # SHA-256 du jeton opaque transmis dans le lien (section 9.3) - le jeton
    # en clair n'est jamais persiste : il n'existe que le temps de construire
    # l'URL inseree dans l'e-mail Resend.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    action_autorisee: Mapped[str] = mapped_column(String(30), nullable=False)
    # Verifie si l'Option B (section 9.1) est retenue - c'est le cas ici (D1).
    approbateur_attendu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id"), nullable=False
    )
    expire_a: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Renseigne a la premiere consommation ; rend le jeton definitivement invalide.
    utilise_a: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ex. etape rendue obsolete par une relance ou une derogation (non exploite
    # tant que les relances, section 9.3/Phase 3, ne sont pas implementees).
    revoque: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cree_a: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
