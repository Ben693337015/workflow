"""
Routes de l'espace de communication bidirectionnelle (ecart n°5, section
4.5 du CDC fonctionnel).

Le manquement decrit par le CDC : le flux standard est strictement
lineaire - si un approbateur a un doute sur un justificatif, sa seule
option est le refus global, obligeant le demandeur a tout ressaisir.
L'exigence : suspendre temporairement le circuit ("En attente
d'informations"), echanger des messages avec le demandeur, puis reprendre
le fil initial (Approbation/Rejet/Signature) une fois les eclaircissements
obtenus.

Generique par construction (route sur Demande, pas sur un processus
precis) : s'applique aussi bien aux conges, aux notes de frais qu'aux
achats, sans code specifique a dupliquer par processus.

Perimetre delibere : la discussion se limite aux deux parties directement
concernees (le demandeur et l'approbateur de l'etape en cours) - le CDC
mentionne aussi "un autre service (ex. la comptabilite)" comme participant
possible, non couvert ici (necessiterait un mecanisme d'invitation de
tiers, hors de cette premiere passe). L'historique reste consultable
indefiniment en base (jamais supprime) - "annexe au dossier final" au sens
ou il n'est jamais detache de la demande, mais n'est pas fusionne dans un
document PDF genere (bon de commande, fiche de confirmation...).
"""
import asyncio
import uuid
from html import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.models.demande import Demande
from app.models.enums import EvenementWebhook, RoleEtape, RoleUtilisateur, StatutDemande, StatutEtape, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.message_clarification import MessageClarification
from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.models.user import Utilisateur
from app.schemas.clarifications import MessageCreate, MessageRead, SuspensionCreate
from app.services import audit, decision_tokens, email_gabarit as g, email_service, stockage_fichiers, webhooks

settings = get_settings()
router = APIRouter(prefix="/api/v1/demandes", tags=["clarifications"])


async def _resoudre_demande(db: AsyncSession, demande_id: str) -> Demande:
    try:
        identifiant = uuid.UUID(demande_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    demande = await db.get(Demande, identifiant)
    if demande is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return demande


async def _etape_active(db: AsyncSession, demande_id: uuid.UUID) -> EtapeWorkflow:
    """
    L'unique étape en attente de décision OU en cours de discussion pour
    cette demande - le moteur de routage séquentiel garantit qu'il n'en
    existe jamais plus d'une à la fois.
    """
    resultat = await db.execute(
        select(EtapeWorkflow)
        .where(
            EtapeWorkflow.demande_id == demande_id,
            EtapeWorkflow.statut.in_([StatutEtape.EN_ATTENTE, StatutEtape.EN_COURS]),
        )
        .order_by(EtapeWorkflow.niveau.desc())
    )
    etape = resultat.scalars().first()
    if etape is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aucune étape active pour cette demande.",
        )
    return etape


async def _acces_autorise_messages(db: AsyncSession, demande: Demande, current_user: Utilisateur) -> bool:
    if current_user.id == demande.demandeur_id or current_user.role == RoleUtilisateur.DRH:
        return True
    resultat = await db.execute(
        select(EtapeWorkflow.approbateur_attendu_id).where(EtapeWorkflow.demande_id == demande.id)
    )
    return current_user.id in {row for row, in resultat.all()}


_PAGE_DEMANDEUR = {
    TypeProcessus.CONGES: "/mes-demandes",
    TypeProcessus.NOTES_FRAIS: "/notes-frais",
    TypeProcessus.ACHATS: "/achats",
}


async def _lien_vers_discussion(db: AsyncSession, demande: Demande, etape: EtapeWorkflow, pour_demandeur: bool) -> str:
    """
    Lien « Ouvrir la discussion » pour l'e-mail. Avant, les e-mails disaient « répondez dans l'espace de
    discussion » SANS aucun lien : le destinataire ne savait pas ou aller (defaut constate en test, 05/10).
    - Demandeur : la page de ses demandes (il y trouve le bouton Discussion).
    - Approbateur : un NOUVEAU lien de decision (le jeton n'existe qu'en empreinte, il ne peut pas etre
      retrouve) ; la page de decision affiche la discussion tant que la demande est en attente de precisions.
      On NE revoque PAS les jetons existants (ecart assume avec « un seul jeton actif », CDC technique 9.3) :
      l'approbateur a deja la page ouverte avec l'ancien lien, et le revoquer la casse en plein echange
      (401 au moment de « Reprendre le workflow » - constate en test navigateur reel, 05/10). Le risque est
      nul : chaque jeton exige la connexion de l'approbateur attendu (Option B) et cesse de servir des que
      l'etape est decidee.
    A appeler AVANT le commit : le jeton est persiste avec le message.
    """
    base = settings.frontend_base_url.rstrip("/")
    if pour_demandeur:
        return f"{base}{_PAGE_DEMANDEUR[demande.processus]}"
    action = "signer" if etape.role == RoleEtape.SIGNATAIRE else "approuver"
    jeton = await decision_tokens.generer_jeton_decision(db, etape.id, action, etape.approbateur_attendu_id)
    return f"{base}/decisions/{jeton}"


@router.post("/{demande_id}/suspendre", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def suspendre_pour_precisions(
    demande_id: str,
    payload: SuspensionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _resoudre_demande(db, demande_id)
    if demande.statut_global != StatutDemande.EN_COURS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette demande n'est pas en cours de décision : impossible de la suspendre.",
        )
    etape = await _etape_active(db, demande.id)
    if current_user.id != etape.approbateur_attendu_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul l'approbateur attendu de cette étape peut demander des précisions.",
        )

    demande.statut_global = StatutDemande.COMPLEMENT_DEMANDE
    etape.statut = StatutEtape.EN_COURS

    message = MessageClarification(demande_id=demande.id, auteur_id=current_user.id, contenu=payload.message)
    db.add(message)
    await db.flush()

    await webhooks.notifier_evenement(db, demande.id, demande.processus, EvenementWebhook.COMPLEMENT_DEMANDE)
    await audit.consigner(
        db,
        action="demande_suspendue_precisions",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"message": payload.message},
    )
    await db.commit()
    await db.refresh(message)

    demandeur = await db.get(Utilisateur, demande.demandeur_id)
    if demandeur is not None:
        try:
            await email_service.envoyer_email(
                destinataire=demandeur.email,
                sujet="💬 Précisions demandées sur votre demande",
                corps_html=(
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        f"<strong>{escape(current_user.nom_complet)}</strong> souhaite quelques précisions avant de "
                        "statuer sur votre demande. Votre réponse permettra de la faire avancer rapidement 🚀"
                    )
                    + g.encart(payload.message, "Sa question", "info", "❓")
                    + g.boutons(
                        ("Ouvrir la discussion",
                         f"{settings.frontend_base_url.rstrip('/')}{_PAGE_DEMANDEUR[demande.processus]}", "primaire"),
                    )
                    + g.note("Astuce : utilisez le bouton « Discussion » sur la demande concernée.")
                ),
            )
        except Exception:
            pass  # section 13.4 : ne doit jamais faire echouer l'action

    return MessageRead(
        id=str(message.id),
        auteur_id=str(message.auteur_id),
        auteur_nom=current_user.nom_complet,
        contenu=message.contenu,
        cree_le=message.cree_le.isoformat(),
    )


@router.post("/{demande_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def envoyer_message(
    demande_id: str,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _resoudre_demande(db, demande_id)
    if demande.statut_global != StatutDemande.COMPLEMENT_DEMANDE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette demande n'est pas en attente de précisions : aucun message possible.",
        )
    etape = await _etape_active(db, demande.id)
    participants = {demande.demandeur_id, etape.approbateur_attendu_id}
    if current_user.id not in participants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne faites pas partie de cet échange.",
        )

    message = MessageClarification(demande_id=demande.id, auteur_id=current_user.id, contenu=payload.contenu)
    db.add(message)
    await db.flush()

    await audit.consigner(
        db,
        action="message_clarification_envoye",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"message": payload.contenu},
    )
    vers_demandeur = current_user.id != demande.demandeur_id
    lien = await _lien_vers_discussion(db, demande, etape, vers_demandeur)
    await db.commit()
    await db.refresh(message)

    destinataire_id = etape.approbateur_attendu_id if current_user.id == demande.demandeur_id else demande.demandeur_id
    destinataire = await db.get(Utilisateur, destinataire_id)
    if destinataire is not None:
        try:
            await email_service.envoyer_email(
                destinataire=destinataire.email,
                sujet="💬 Nouveau message sur une demande en attente de précisions",
                corps_html=(
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(f"<strong>{escape(current_user.nom_complet)}</strong> vient de répondre dans la discussion 🙂")
                    + g.encart(payload.contenu, "Son message", "info", "💬")
                    + g.boutons(("Ouvrir la discussion et répondre", lien, "primaire"))
                ),
            )
        except Exception:
            pass  # section 13.4 : ne doit jamais faire echouer l'action

    return MessageRead(
        id=str(message.id),
        auteur_id=str(message.auteur_id),
        auteur_nom=current_user.nom_complet,
        contenu=message.contenu,
        cree_le=message.cree_le.isoformat(),
    )


@router.get("/{demande_id}/messages", response_model=list[MessageRead])
async def lister_messages(
    demande_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _resoudre_demande(db, demande_id)
    if not await _acces_autorise_messages(db, demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cette discussion.")

    resultat = await db.execute(
        select(MessageClarification)
        .where(MessageClarification.demande_id == demande.id)
        .order_by(MessageClarification.cree_le)
    )
    messages = resultat.scalars().all()
    auteurs = {
        u.id: u.nom_complet
        for u in (
            await db.execute(
                select(Utilisateur).where(Utilisateur.id.in_({m.auteur_id for m in messages}))
            )
        ).scalars()
    }
    fichiers = {}
    if messages:
        pieces = await db.execute(
            select(PieceJointe).where(PieceJointe.message_id.in_({m.id for m in messages}))
        )
        fichiers = {p.message_id: p.nom_original for p in pieces.scalars()}
    return [
        MessageRead(
            id=str(m.id),
            auteur_id=str(m.auteur_id),
            auteur_nom=auteurs.get(m.auteur_id, "Utilisateur inconnu"),
            contenu=m.contenu,
            cree_le=m.cree_le.isoformat(),
            fichier_nom=fichiers.get(m.id),
        )
        for m in messages
    ]


@router.post(
    "/{demande_id}/messages/avec-fichier", response_model=MessageRead, status_code=status.HTTP_201_CREATED
)
async def envoyer_message_avec_fichier(
    demande_id: str,
    contenu: str = Form(..., min_length=1, max_length=2000),
    fichier: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """
    Depot d'une piece complementaire au sein de l'espace de discussion (CDC
    section 4.5 : "Les echanges de messages et le depot de pieces
    complementaires doivent s'effectuer au sein de cet espace"). Ecart trouve
    en verifiant cette fonctionnalite (27/09) : seuls des messages texte
    existaient. Memes gardes que l'envoi d'un message simple (demande
    suspendue, deux parties concernees), plus la validation de fichier
    partagee avec le contrat des achats (types, taille : stockage_fichiers.TAILLE_MAX_MO).
    """
    demande = await _resoudre_demande(db, demande_id)
    if demande.statut_global != StatutDemande.COMPLEMENT_DEMANDE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette demande n'est pas en attente de précisions : aucun message possible.",
        )
    etape = await _etape_active(db, demande.id)
    if current_user.id not in {demande.demandeur_id, etape.approbateur_attendu_id}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vous ne faites pas partie de cet échange.")

    octets = await stockage_fichiers.lire_depot(fichier)
    erreur_fichier = stockage_fichiers.verifier_fichier(fichier.content_type, octets)
    if erreur_fichier:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=erreur_fichier)

    message = MessageClarification(demande_id=demande.id, auteur_id=current_user.id, contenu=contenu)
    db.add(message)
    await db.flush()
    nom = (fichier.filename or "piece")[:255]
    db.add(
        PieceJointe(
            demande_id=demande.id,
            message_id=message.id,
            categorie=CategoriePiece.DISCUSSION.value,
            nom_original=nom,
            cle_stockage=await asyncio.to_thread(stockage_fichiers.enregistrer_fichier, octets, nom),
        )
    )
    await audit.consigner(
        db,
        action="message_clarification_envoye",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"message": contenu, "fichier": nom},
    )
    vers_demandeur = current_user.id != demande.demandeur_id
    lien = await _lien_vers_discussion(db, demande, etape, vers_demandeur)
    await db.commit()
    await db.refresh(message)

    destinataire_id = etape.approbateur_attendu_id if current_user.id == demande.demandeur_id else demande.demandeur_id
    destinataire = await db.get(Utilisateur, destinataire_id)
    if destinataire is not None:
        try:
            await email_service.envoyer_email(
                destinataire=destinataire.email,
                sujet="📎 Nouveau message avec pièce jointe sur une demande en attente de précisions",
                corps_html=(
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        f"<strong>{escape(current_user.nom_complet)}</strong> vient de répondre dans la discussion "
                        "et a joint un document 🙂"
                    )
                    + g.encart(contenu, "Son message", "info", "💬")
                    + g.carte([("Pièce jointe", nom)])
                    + g.note("Le document est à consulter dans l'espace de discussion.")
                    + g.boutons(("Ouvrir la discussion et répondre", lien, "primaire"))
                ),
            )
        except Exception:
            pass  # section 13.4 : ne doit jamais faire echouer l'action

    return MessageRead(
        id=str(message.id),
        auteur_id=str(message.auteur_id),
        auteur_nom=current_user.nom_complet,
        contenu=message.contenu,
        cree_le=message.cree_le.isoformat(),
        fichier_nom=nom,
    )


@router.get("/{demande_id}/messages/{message_id}/fichier")
async def telecharger_fichier_message(
    demande_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _resoudre_demande(db, demande_id)
    if not await _acces_autorise_messages(db, demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cette discussion.")
    try:
        identifiant = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pièce jointe introuvable.")
    # Le message doit appartenir a CETTE demande : sans ce filtre, un
    # participant d'une demande pourrait lire la piece d'une autre en
    # combinant son propre demande_id avec le message_id d'un tiers.
    resultat = await db.execute(
        select(PieceJointe).where(
            PieceJointe.message_id == identifiant, PieceJointe.demande_id == demande.id
        )
    )
    piece = resultat.scalars().first()
    if piece is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pièce jointe introuvable.")
    return Response(
        content=await asyncio.to_thread(stockage_fichiers.lire_fichier, piece.cle_stockage),
        media_type="application/octet-stream",
        headers={"Content-Disposition": stockage_fichiers.en_tete_telechargement(piece.nom_original)},
    )


@router.post("/{demande_id}/reprendre", status_code=status.HTTP_200_OK)
async def reprendre_le_workflow(
    demande_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _resoudre_demande(db, demande_id)
    if demande.statut_global != StatutDemande.COMPLEMENT_DEMANDE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette demande n'est pas en attente de précisions.",
        )
    etape = await _etape_active(db, demande.id)
    if current_user.id != etape.approbateur_attendu_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul l'approbateur attendu de cette étape peut reprendre le workflow.",
        )

    demande.statut_global = StatutDemande.EN_COURS
    etape.statut = StatutEtape.EN_ATTENTE

    await audit.consigner(
        db,
        action="demande_reprise_apres_precisions",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={},
    )
    await db.commit()

    return {"id": str(demande.id), "statut_global": demande.statut_global.value}
