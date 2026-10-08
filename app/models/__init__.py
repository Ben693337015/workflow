"""
Point d'entree unique des modeles SQLAlchemy.

Importer ce module (ou app.core.database.Base.metadata apres cet import)
garantit que les entites du CDC technique (section 4), plus les deux
entites ajoutées suite à la revue comparative (TypeConge, JourFerie), sont
enregistrees aupres de la Base declarative avant toute generation de
migration Alembic.
"""
from app.models.abonnement_webhook import AbonnementWebhook
from app.models.bon_commande import BonCommande, CompteurBonCommande
from app.models.demande import Demande
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.etape_workflow import EtapeWorkflow
from app.models.jeton_compte import JetonCompte
from app.models.jeton_decision import JetonDecision
from app.models.jour_ferie import JourFerie
from app.models.journal_audit import JournalAudit
from app.models.message_clarification import MessageClarification
from app.models.mouvement_conges import MouvementConges
from app.models.piece_jointe import PieceJointe
from app.models.solde_conges import SoldeConges
from app.models.taux_change import TauxChange
from app.models.type_conge import TypeConge
from app.models.type_demande import TypeDemande
from app.models.user import Utilisateur

__all__ = [
    "AbonnementWebhook",
    "BonCommande",
    "CompteurBonCommande",
    "Demande",
    "EnveloppeBudgetaire",
    "EtapeWorkflow",
    "JetonCompte",
    "JetonDecision",
    "JourFerie",
    "JournalAudit",
    "MessageClarification",
    "MouvementConges",
    "PieceJointe",
    "SoldeConges",
    "TauxChange",
    "TypeConge",
    "TypeDemande",
    "Utilisateur",
]
