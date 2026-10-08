"""
Pieces jointes d'une demande, generiques aux trois processus (CDC fonctionnel section 3) :
justificatif d'absence des conges, recu fiscal des notes de frais, documents
complementaires des achats. Le depot est facultatif : la demande existe d'abord, la piece
s'y attache ensuite - un echec d'envoi ne bloque jamais la demande.
"""
import asyncio
import uuid
from html import escape

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.demande import Demande
from app.models.enums import StatutDemande, StatutEtape
from app.models.etape_workflow import EtapeWorkflow
from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.models.user import Utilisateur
from app.schemas.pieces_jointes import PieceJointeRead
from app.services import audit, email_gabarit as g, email_service, pieces, pieces_email, stockage_fichiers
from app.services.rappels import LIBELLES_PROCESSUS

router = APIRouter(prefix="/api/v1/demandes", tags=["pieces-jointes"])


async def _demande(db: AsyncSession, demande_id: str) -> Demande:
    try:
        identifiant = uuid.UUID(demande_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    demande = await db.get(Demande, identifiant)
    if demande is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return demande


@router.post("/{demande_id}/pieces-jointes", response_model=PieceJointeRead, status_code=status.HTTP_201_CREATED)
async def deposer_piece_jointe(
    demande_id: str,
    fichier: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _demande(db, demande_id)
    if current_user.id not in (demande.demandeur_id, demande.initiee_par_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seul le demandeur peut ajouter une pièce.")
    # Une piece peut etre ajoutee tant que la demande n'est pas close, y compris pendant une
    # suspension pour precisions (CDC 4.5) : c'est precisement quand on en demande.
    if demande.statut_global not in (StatutDemande.EN_COURS, StatutDemande.COMPLEMENT_DEMANDE):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette demande est close : plus de pièce possible.")

    deja = await db.scalar(
        select(func.count()).select_from(PieceJointe).where(
            PieceJointe.demande_id == demande.id, PieceJointe.categorie != CategoriePiece.DISCUSSION.value
        )
    )
    if deja >= pieces.MAX_PIECES_PAR_DEMANDE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nombre maximal de pièces atteint ({pieces.MAX_PIECES_PAR_DEMANDE}).",
        )

    octets = await stockage_fichiers.lire_depot(fichier)
    erreur = stockage_fichiers.verifier_fichier(fichier.content_type, octets)
    if erreur:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=erreur)

    nom = (fichier.filename or "piece")[:255]
    piece = PieceJointe(
        demande_id=demande.id,
        nom_original=nom,
        cle_stockage=await asyncio.to_thread(stockage_fichiers.enregistrer_fichier, octets, nom),
        categorie=pieces.CATEGORIE_PAR_PROCESSUS[demande.processus].value,
    )
    db.add(piece)
    await db.flush()
    await audit.consigner(
        db,
        action="piece_jointe_ajoutee",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"fichier": nom, "categorie": piece.categorie},
    )
    await db.commit()
    await _prevenir_approbateur(db, demande, current_user, piece.id)
    return PieceJointeRead(id=str(piece.id), nom=nom, categorie=piece.categorie)


async def _prevenir_approbateur(db: AsyncSession, demande: Demande, demandeur: Utilisateur, piece_id: uuid.UUID) -> None:
    """
    Les conges et les notes de frais recoivent leurs pieces APRES la soumission (la demande existe d'abord) : l'e-mail
    de decision est donc deja parti sans elles. Chaque depot declenche un message a l'approbateur en attente, avec la
    piece EN PIECE JOINTE (ou, si elle est trop volumineuse, nommee avec un renvoi vers l'ecran de decision).
    Best-effort (section 13.4) : un echec d'e-mail ne remet jamais en cause le depot, deja enregistre.
    """
    try:
        etape = (
            await db.execute(
                select(EtapeWorkflow)
                .where(EtapeWorkflow.demande_id == demande.id, EtapeWorkflow.statut == StatutEtape.EN_ATTENTE)
                .order_by(EtapeWorkflow.niveau)
            )
        ).scalars().first()
        approbateur = await db.get(Utilisateur, etape.approbateur_attendu_id) if etape else None
        if approbateur is None:
            return
        pieces_mail = await pieces_email.preparer(db, demande.id, seulement=piece_id)
        await email_service.envoyer_email(
            destinataire=approbateur.email,
            sujet=f"📎 Pièce ajoutée — {LIBELLES_PROCESSUS[demande.processus]} de {demandeur.nom_complet}",
            corps_html=(
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"<strong>{escape(demandeur.nom_complet)}</strong> vient d'ajouter une pièce à sa "
                    f"{LIBELLES_PROCESSUS[demande.processus]} en attente de votre décision 📎"
                )
                + pieces_email.bloc_html(pieces_mail)
                + g.note(
                    "🔒 Pour décider, utilisez les boutons du premier message reçu (ou demandez une relance au demandeur : "
                    "elle renvoie de nouveaux liens)."
                )
            ),
            pieces_jointes=pieces_mail.jointes,
        )
    except Exception:
        pass  # section 13.4 : ne doit jamais faire echouer le depot


@router.get("/{demande_id}/pieces-jointes", response_model=list[PieceJointeRead])
async def lister_pieces_jointes(
    demande_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _demande(db, demande_id)
    if not await pieces.peut_consulter_demande(db, demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ces pièces.")
    return (await pieces.pieces_par_demande(db, [demande.id])).get(demande.id, [])


@router.get("/{demande_id}/pieces-jointes/{piece_id}")
async def telecharger_piece_jointe(
    demande_id: str,
    piece_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _demande(db, demande_id)
    if not await pieces.peut_consulter_demande(db, demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ces pièces.")
    try:
        identifiant = uuid.UUID(piece_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pièce introuvable.")
    # La piece doit appartenir a CETTE demande (sinon un participant lirait la piece d'une
    # autre demande en combinant son demande_id avec un piece_id tiers) et ne pas etre une
    # piece de discussion (elle a sa propre route, avec ses propres regles d'acces).
    resultat = await db.execute(
        select(PieceJointe).where(
            PieceJointe.id == identifiant,
            PieceJointe.demande_id == demande.id,
            PieceJointe.categorie != CategoriePiece.DISCUSSION.value,
        )
    )
    piece = resultat.scalars().first()
    if piece is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pièce introuvable.")
    return Response(
        content=await asyncio.to_thread(stockage_fichiers.lire_fichier, piece.cle_stockage),
        media_type="application/octet-stream",
        headers={"Content-Disposition": stockage_fichiers.en_tete_telechargement(piece.nom_original)},
    )
