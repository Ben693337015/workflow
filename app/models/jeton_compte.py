"""
Entite Jetons de compte - invitation initiale et reinitialisation de mot de
passe (section 5 du CDC technique).

Ecart identifie et corrige (revue du 15/09) : le CDC exige explicitement un
mecanisme de reinitialisation par e-mail, avec un lien a usage unique et
courte duree de vie, construit sur le meme mecanisme cryptographique que
les jetons de decision (section 9). Il n'existait pas du tout avant cette
date, et la creation de compte par le DRH (app/routers/utilisateurs.py)
exigeait que le DRH choisisse et transmette lui-meme le mot de passe
initial de chaque employe - une pratique non securisee que la plateforme
est censee remplacer.

Meme principe que JetonDecision (section 4.2.5) : jeton opaque
(secrets.token_urlsafe), seule l'empreinte SHA-256 est persistee.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import TypeJetonCompte


class JetonCompte(Base):
    __tablename__ = "jetons_compte"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("utilisateurs.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    type_jeton: Mapped[TypeJetonCompte] = mapped_column(
        Enum(TypeJetonCompte, name="type_jeton_compte", native_enum=False), nullable=False
    )
    expire_a: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    utilise_a: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cree_a: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    # Ecart identifié et corrigé (revue du 16/09, suite au test réel de bout
    # en bout) : sans ce champ, un e-mail d'invitation/réinitialisation qui
    # échoue à l'envoi (Resend indisponible, domaine mal configuré...)
    # perdait le jeton en clair définitivement (par conception, §9.3), sans
    # aucun moyen de le renvoyer - confirmé par un test réel où la seule
    # option restante était une intervention manuelle en base.
    revoque: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
