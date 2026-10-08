"use client";

import { ChampFichier } from "@/components/champ-fichier";
import * as React from "react";
import { Paperclip } from "lucide-react";
import { Alert, Label, Textarea } from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  envoyerMessage,
  envoyerMessageAvecFichier,
  listerMessages,
  reprendreDemande,
  telechargerFichierMessage,
} from "@/lib/api";
import { messageTailleFichier } from "@/lib/fichiers";
import { enregistrerFichier } from "@/lib/telechargement";
import type { MessageClarification } from "@/types";

/** Intervalle de rafraichissement de la discussion (ms). */
export const INTERVALLE_RAFRAICHISSEMENT_MS = 10_000;

/**
 * Espace de discussion parallele au circuit (ecart n°5, section 4.5 du CDC) :
 * echange entre le demandeur et l'approbateur dont la decision est suspendue,
 * avec depot de pieces complementaires.
 *
 * La discussion se rafraichit d'elle-meme : sans cela, ce n'est pas un
 * echange - une reponse n'apparaitrait qu'apres un rechargement de page
 * (ecart trouve en verifiant la communication bidirectionnelle, 27/09).
 *
 * `onReprise` n'est fourni que cote approbateur (seul lui peut reprendre le
 * workflow - le backend le verifie de toute facon, ce n'est qu'une
 * commodite d'affichage).
 */
/** Date et heure locales d'un message (« 01/10/2026 14:32 »). Vide si illisible. */
function formaterDateMessage(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export function DiscussionPanel({
  demandeId,
  onReprise,
  utilisateurId,
}: {
  demandeId: string;
  onReprise?: () => void;
  /** Utilisateur connecte : ses propres messages sont reperes par « (vous) ». */
  utilisateurId?: string;
}) {
  const [messages, setMessages] = React.useState<MessageClarification[]>([]);
  const [contenu, setContenu] = React.useState("");
  const [fichier, setFichier] = React.useState<File | null>(null);
  const [cleFichier, setCleFichier] = React.useState(0);
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);
  const [aCharge, setACharge] = React.useState(false);
  const liste = React.useRef<HTMLUListElement>(null);

  const charger = React.useCallback(() => {
    listerMessages(demandeId)
      .then((reponse) => {
        setMessages(reponse);
        setACharge(true);
        setErreur(null);
      })
      .catch((err) => setErreur(err instanceof ApiError ? err.message : "Impossible de charger la discussion."));
  }, [demandeId]);

  React.useEffect(() => {
    charger();
    const minuteur = setInterval(charger, INTERVALLE_RAFRAICHISSEMENT_MS);
    return () => clearInterval(minuteur);
  }, [charger]);

  // Descend sur le DERNIER message a chaque nouveau message (envoi, reponse de l'autre partie) : sans cela la
  // liste restait en haut et le message envoye ou recu etait cache en bas.
  React.useEffect(() => {
    const el = liste.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  async function onEnvoyer(e: React.FormEvent) {
    e.preventDefault();
    if (!contenu.trim()) return;
    setErreur(null);
    const tropGros = messageTailleFichier(fichier);
    if (tropGros) {
      setErreur(tropGros);
      return;
    }
    setEnCours(true);
    try {
      if (fichier) {
        await envoyerMessageAvecFichier(demandeId, contenu.trim(), fichier);
      } else {
        await envoyerMessage(demandeId, contenu.trim());
      }
      setContenu("");
      setFichier(null);
      setCleFichier((n) => n + 1); // vide le champ fichier (un <input type=file> ne se controle pas)
      charger();
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Envoi impossible.");
    } finally {
      setEnCours(false);
    }
  }

  async function onTelecharger(m: MessageClarification) {
    try {
      enregistrerFichier(await telechargerFichierMessage(demandeId, m.id), m.fichier_nom ?? "piece");
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Téléchargement impossible.");
    }
  }

  async function onReprendre() {
    setErreur(null);
    setEnCours(true);
    try {
      await reprendreDemande(demandeId);
      onReprise?.();
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Reprise impossible.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ul
        ref={liste}
        aria-live="polite"
        aria-label="Messages de la discussion"
        className="flex max-h-[40dvh] flex-col gap-2 overflow-y-auto overflow-x-hidden"
      >
        {aCharge && messages.length === 0 && (
          <li className="rounded-lg bg-canvas p-3 text-[13px] text-ink-dim">Aucun message pour le moment.</li>
        )}
        {messages.map((m) => (
          <li
            key={m.id}
            className={`min-w-0 rounded-lg p-3 text-[13.5px] ${
              utilisateurId && m.auteur_id === utilisateurId ? "bg-accent-soft" : "bg-canvas"
            }`}
          >
            <p className="mb-0.5 flex items-baseline justify-between gap-3 text-[12px] font-medium text-ink-dim">
              <span className="min-w-0 truncate">
                {m.auteur_nom}
                {utilisateurId && m.auteur_id === utilisateurId ? " (vous)" : ""}
              </span>
              <time className="shrink-0 font-normal text-ink-faint" dateTime={m.cree_le}>
                {formaterDateMessage(m.cree_le)}
              </time>
            </p>
            <p className="text-ink">{m.contenu}</p>
            {m.fichier_nom && (
              <button
                type="button"
                onClick={() => onTelecharger(m)}
                className="mt-1.5 flex min-w-0 max-w-full items-center gap-1 text-[12.5px] text-accent-text hover:underline"
              >
                <Paperclip className="h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 truncate" title={m.fichier_nom}>
                  {m.fichier_nom}
                </span>
              </button>
            )}
          </li>
        ))}
      </ul>

      <form className="flex flex-col gap-2" onSubmit={onEnvoyer}>
        <Label htmlFor={`message-${demandeId}`}>Votre message</Label>
        <Textarea
          id={`message-${demandeId}`}
          value={contenu}
          onChange={(e) => setContenu(e.target.value)}
          maxLength={2000}
        />
        <Label htmlFor={`piece-${demandeId}`}>Pièce complémentaire (facultatif)</Label>
        <ChampFichier
          key={cleFichier}
          id={`piece-${demandeId}`}
         
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          onChange={(e) => setFichier(e.target.files?.[0] ?? null)}
        />
        <Button type="submit" variant="outline" disabled={enCours || !contenu.trim()}>
          Envoyer
        </Button>
      </form>

      {erreur && <Alert variant="destructive">{erreur}</Alert>}

      {onReprise && (
        <Button type="button" onClick={onReprendre} disabled={enCours}>
          Reprendre le workflow
        </Button>
      )}
    </div>
  );
}
