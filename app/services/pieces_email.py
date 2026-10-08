"""
Pieces jointes des demandes dans les e-mails (justificatif d'absence, recus de frais, contrat et complements d'achat).

Source officielle (Resend, "Attachments") : un e-mail ne peut pas depasser 40 Mo, pieces jointes comprises APRES
encodage base64 (+ ~33 %). Plafond retenu ici : 25 Mo d'octets bruts (~33,4 Mo encodes), qui laisse de la marge au
corps HTML. Une piece qui ne tient plus est OMISE de l'envoi mais NOMMEE dans le message, avec le renvoi vers l'ecran
de decision : le destinataire sait toujours qu'elle existe.

Regles :
- seules les pieces du DOSSIER sont jointes (jamais celles de la discussion, qui ont leurs propres regles d'acces) ;
- seuls les destinataires deja autorises a consulter la demande (`pieces.peut_consulter_demande`) en recoivent :
  approbateur de l'etape, comptabilite pour une note de frais validee ;
- tout echec de lecture est absorbe (section 13.4) : l'e-mail part sans la piece fautive, jamais l'inverse.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.services import email_gabarit as g
from app.services import stockage_fichiers

logger = logging.getLogger(__name__)

# 25 Mo bruts => ~33,4 Mo en base64 : sous la limite de 40 Mo de Resend, avec de la marge pour le HTML.
PLAFOND_OCTETS = 25 * 1024 * 1024


@dataclass
class PiecesEmail:
    """Pieces pretes a joindre (nom, octets) et noms des pieces qui n'ont pas pu l'etre."""

    jointes: list[tuple[str, bytes]] = field(default_factory=list)
    omises: list[str] = field(default_factory=list)

    @property
    def vide(self) -> bool:
        return not self.jointes and not self.omises


def _nom_unique(nom: str, deja: set[str]) -> str:
    """Deux pieces peuvent porter le meme nom (scan.pdf) : on numerote pour que le destinataire les distingue."""
    if nom not in deja:
        return nom
    base, point, extension = nom.rpartition(".")
    if not point:
        base, extension = nom, ""
    suffixe = f".{extension}" if point else ""
    compteur = 2
    while f"{base} ({compteur}){suffixe}" in deja:
        compteur += 1
    return f"{base} ({compteur}){suffixe}"


async def preparer(
    db: AsyncSession, demande_id: uuid.UUID, *, seulement: uuid.UUID | None = None
) -> PiecesEmail:
    """
    Charge les pieces du dossier d'une demande (ou UNE seule via `seulement`, pour l'envoi qui suit un depot).
    Ne leve jamais d'exception : au pire, un resultat vide.
    """
    resultat = PiecesEmail()
    try:
        requete = select(PieceJointe).where(
            PieceJointe.demande_id == demande_id, PieceJointe.categorie != CategoriePiece.DISCUSSION.value
        )
        if seulement is not None:
            requete = requete.where(PieceJointe.id == seulement)
        pieces = (await db.execute(requete.order_by(PieceJointe.deposee_le))).scalars().all()
        total, noms = 0, set()
        for piece in pieces:
            try:
                octets = await asyncio.to_thread(stockage_fichiers.lire_fichier, piece.cle_stockage)
            except Exception:
                logger.exception("Piece %s illisible : non jointe a l'e-mail", piece.id)
                resultat.omises.append(piece.nom_original)
                continue
            if total + len(octets) > PLAFOND_OCTETS:
                resultat.omises.append(piece.nom_original)
                continue
            nom = _nom_unique(piece.nom_original, noms)
            noms.add(nom)
            total += len(octets)
            resultat.jointes.append((nom, octets))
    except Exception:
        logger.exception("Preparation des pieces jointes de l'e-mail impossible (demande %s)", demande_id)
        return PiecesEmail()
    return resultat


def bloc_html(pieces: PiecesEmail) -> str:
    """Encart « pieces jointes » du message ; chaine vide s'il n'y a aucune piece."""
    if pieces.vide:
        return ""
    lignes = [("📎 " + nom, "jointe à ce message") for nom, _ in pieces.jointes]
    lignes += [("📁 " + nom, "à consulter dans l'écran de décision") for nom in pieces.omises]
    titre = f"Pièces du dossier ({len(lignes)})"
    entete = f'<p style="margin:12px 0 4px 0;font-size:13px;font-weight:700;color:#12151c;">{titre}</p>'
    note = (
        g.note(
            "Certaines pièces sont trop volumineuses pour un e-mail : elles restent consultables en ligne, "
            "depuis l'écran de décision."
        )
        if pieces.omises
        else ""
    )
    return entete + g.carte(lignes) + note
