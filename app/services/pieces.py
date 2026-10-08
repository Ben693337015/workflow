"""
Pieces jointes d'une demande : recu des notes de frais, justificatif d'absence des conges
(CDC fonctionnel section 3, "donnees cles a capturer"), contrat et documents
complementaires des achats (CDC 2.1 : "un ou plusieurs documents").

Ecart trouve par l'audit de conformite du 28/09 : aucune de ces pieces (hors contrat des
achats) ne pouvait etre deposee, et l'approbateur ne pouvait consulter aucune piece - le
contrat des achats n'etait accessible que par un chemin d'API cite dans un e-mail.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demande import Demande
from app.models.enums import RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.models.user import Utilisateur
from app.schemas.pieces_jointes import PieceJointeRead

# Categorie attribuee a une piece deposee apres coup, selon le processus : le client ne la choisit pas.
CATEGORIE_PAR_PROCESSUS = {
    TypeProcessus.CONGES: CategoriePiece.JUSTIFICATIF,
    TypeProcessus.NOTES_FRAIS: CategoriePiece.RECU,
    TypeProcessus.ACHATS: CategoriePiece.COMPLEMENT,
}
MAX_PIECES_PAR_DEMANDE = 10


async def pieces_par_demande(db: AsyncSession, demande_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PieceJointeRead]]:
    """Pieces de dossier (hors discussion, qui a sa propre liste) regroupees par demande."""
    if not demande_ids:
        return {}
    resultat = await db.execute(
        select(PieceJointe)
        .where(PieceJointe.demande_id.in_(demande_ids), PieceJointe.categorie != CategoriePiece.DISCUSSION.value)
        .order_by(PieceJointe.deposee_le)
    )
    regroupees: dict[uuid.UUID, list[PieceJointeRead]] = {}
    for piece in resultat.scalars():
        regroupees.setdefault(piece.demande_id, []).append(
            PieceJointeRead(id=str(piece.id), nom=piece.nom_original, categorie=piece.categorie)
        )
    return regroupees


async def peut_consulter_demande(db: AsyncSession, demande: Demande, utilisateur: Utilisateur) -> bool:
    """
    Demandeur, DRH (audit), approbateur d'une etape de cette demande (passee, en cours ou a venir) - et, pour
    les seules NOTES DE FRAIS VALIDEES, la Direction financiere et le Controleur de gestion : la comptabilite doit
    voir les recus pour rembourser (ecran de synthese). Rien de plus : ni notes en cours, ni achats, ni conges.
    """
    if utilisateur.id in (demande.demandeur_id, demande.initiee_par_id) or utilisateur.role == RoleUtilisateur.DRH:
        return True
    if (
        utilisateur.role in (RoleUtilisateur.DIRECTION_FINANCIERE, RoleUtilisateur.CONTROLEUR_DE_GESTION)
        and demande.processus == TypeProcessus.NOTES_FRAIS
        and demande.statut_global == StatutDemande.TERMINEE
    ):
        return True
    resultat = await db.execute(
        select(EtapeWorkflow.id).where(
            EtapeWorkflow.demande_id == demande.id, EtapeWorkflow.approbateur_attendu_id == utilisateur.id
        )
    )
    return resultat.first() is not None
