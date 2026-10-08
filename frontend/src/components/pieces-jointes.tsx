"use client";

import { ChampFichier } from "@/components/champ-fichier";
import * as React from "react";
import { messageTailleFichier } from "@/lib/fichiers";
import { Paperclip } from "lucide-react";
import { ApiError, deposerPieceJointe, telechargerPieceJointe } from "@/lib/api";
import { enregistrerFichier } from "@/lib/telechargement";
import type { PieceJointe } from "@/types";

const LIBELLES: Record<string, string> = {
  contrat: "Contrat",
  recu: "Reçu",
  justificatif: "Justificatif d'absence",
  complement: "Document complémentaire",
};

/**
 * Pieces d'un dossier (recu d'une note de frais, justificatif d'absence, contrat et documents
 * complementaires d'un achat) : telechargement, et depot facultatif par le demandeur.
 *
 * Utilise par l'approbateur sur la page de decision (consultation seule) et par le demandeur
 * dans ses listes. Avant l'audit de conformite du 28/09, aucune piece n'etait consultable depuis
 * l'application : l'approbateur d'un achat n'avait qu'un chemin d'API cite dans un e-mail.
 */
export function PiecesJointes({
  demandeId,
  pieces,
  peutAjouter = false,
  onAjoutee,
}: {
  demandeId: string;
  pieces: PieceJointe[];
  peutAjouter?: boolean;
  onAjoutee?: () => void;
}) {
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);
  const [cle, setCle] = React.useState(0);

  async function telecharger(piece: PieceJointe) {
    setErreur(null);
    try {
      enregistrerFichier(await telechargerPieceJointe(demandeId, piece.id), piece.nom);
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Téléchargement impossible.");
    }
  }

  async function ajouter(fichier: File | undefined) {
    if (!fichier) return;
    setErreur(null);
    const tropGros = messageTailleFichier(fichier);
    if (tropGros) {
      setErreur(tropGros);
      setCle((n) => n + 1);
      return;
    }
    setEnCours(true);
    try {
      await deposerPieceJointe(demandeId, fichier);
      onAjoutee?.();
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Envoi impossible.");
    } finally {
      setEnCours(false);
      setCle((n) => n + 1); // vide le champ : on peut deposer le meme fichier apres un echec
    }
  }

  return (
    <div className="flex flex-col gap-1">
      {pieces.map((piece) => (
        <button
          key={piece.id}
          type="button"
          onClick={() => telecharger(piece)}
          title={LIBELLES[piece.categorie] ?? piece.categorie}
          className="flex max-w-[11rem] items-center gap-1 text-left text-[12.5px] text-accent-text hover:underline"
        >
          <Paperclip className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 truncate" title={piece.nom}>
            {piece.nom}
          </span>
        </button>
      ))}
      {peutAjouter && (
        <ChampFichier compact
          key={cle}
         
          aria-label="Ajouter une pièce à cette demande"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          disabled={enCours}
          onChange={(e) => ajouter(e.target.files?.[0])}
        />
      )}
      {erreur && <p className="text-[12px] text-danger">{erreur}</p>}
    </div>
  );
}
