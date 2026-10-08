"""Entite Etapes de workflow : une ligne par destinataire d'une demande (section 4 / 7 / 8)."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, DateTime, Enum, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import RoleEtape, StatutEtape


class EtapeWorkflow(Base):
    __tablename__ = "etapes_workflow"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    demande_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("demandes.id"), nullable=False
    )
    niveau: Mapped[int] = mapped_column(Integer, nullable=False)  # ordre de reception (section 7)
    role: Mapped[RoleEtape] = mapped_column(Enum(RoleEtape, name="role_etape", native_enum=False), nullable=False)
    approbateur_attendu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id"), nullable=False
    )
    statut: Mapped[StatutEtape] = mapped_column(
        Enum(StatutEtape, name="statut_etape", native_enum=False), nullable=False, default=StatutEtape.EN_ATTENTE
    )
    # Ecart n°4 (section 4.4 du CDC fonctionnel) : marque une etape comme
    # relevant du circuit d'arbitrage exceptionnel (derogation motivee par
    # le demandeur, ou depassement d'enveloppe budgetaire detecte
    # automatiquement) plutot que du circuit standard. Une "justification
    # d'acceptation" est alors obligatoire de la part de l'arbitre en cas
    # d'approbation (app/routers/decisions.py), en plus du commentaire deja
    # obligatoire en cas de refus.
    est_derogation: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Rappels automatiques (CDC 2.4). `cree_le` n'existait pas : impossible de
    # savoir depuis quand une etape attendait une decision. `dernier_rappel_le`
    # sert aussi de reservation atomique entre plusieurs instances du backend
    # (voir app/services/rappels.py) : un seul rappel par periode, sans doublon.
    cree_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now()
    )
    dernier_rappel_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nombre_rappels: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Ecart corrige (revue du 15/09) : les champs jeton_decision (en clair)
    # et jeton_utilise vivaient ici avant cette date - design pre-V2.7 que
    # le CDC decrit lui-meme comme deja depasse. Le jeton est desormais une
    # entite a part entiere (JetonDecision, section 4.2.5) ; la reutilisation
    # est bloquee par `statut` (qui quitte EN_ATTENTE des la premiere decision)
    # ET par `utilise_a` sur le jeton lui-meme (section 9.3).
    date_reponse: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ecart identifie et corrige (revue du 27/09) : le role Signataire
    # (section 8 - "Capturer une signature a l'ecran, ou refuser") etait
    # traite exactement comme un role Approbateur ordinaire (meme action
    # "approuver", aucune signature reellement capturee). Reference vers
    # l'image de la signature capturee (PNG), via le meme point d'abstraction
    # de stockage que les pieces jointes (app/services/stockage_fichiers.py) -
    # rempli uniquement pour une decision "signer" (jamais "approuver"/"refuser").
    signature_cle_stockage: Mapped[str | None] = mapped_column(Text, nullable=True)

    demande: Mapped["Demande"] = relationship(back_populates="etapes")
