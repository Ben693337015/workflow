"use client";

import * as React from "react";
import { ApiError } from "@/lib/api";

/**
 * Boutons Annuler / Relancer, partagés par les congés, notes de frais et achats (parité ajoutée le
 * 28/09 : ces actions n'existaient que pour les congés). Rendu compact (texte, pas de bouton plein)
 * pour rester dans une cellule de tableau, à l'identique du bouton Annuler déjà présent pour les
 * congés.
 */
export function ActionsDemande({
  demandeId,
  peutAnnuler,
  peutRelancer,
  annuler,
  relancer,
  onChange,
}: {
  demandeId: string;
  peutAnnuler: boolean;
  peutRelancer: boolean;
  annuler: (id: string) => Promise<{ id: string; statut_global: string }>;
  relancer: (id: string) => Promise<{ id: string; email_envoye: boolean; detail: string }>;
  onChange: () => void;
}) {
  const [enCours, setEnCours] = React.useState(false);
  const [message, setMessage] = React.useState<{ texte: string; erreur: boolean } | null>(null);

  async function onAnnuler() {
    setMessage(null);
    setEnCours(true);
    try {
      await annuler(demandeId);
      onChange();
    } catch (err) {
      setMessage({ texte: err instanceof ApiError ? err.message : "Impossible d'annuler cette demande.", erreur: true });
    } finally {
      setEnCours(false);
    }
  }

  async function onRelancer() {
    setMessage(null);
    setEnCours(true);
    try {
      const resultat = await relancer(demandeId);
      setMessage({ texte: resultat.detail, erreur: !resultat.email_envoye });
    } catch (err) {
      setMessage({ texte: err instanceof ApiError ? err.message : "Impossible de relancer cette demande.", erreur: true });
    } finally {
      setEnCours(false);
    }
  }

  if (!peutAnnuler && !peutRelancer) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-3">
        {peutRelancer && (
          <button onClick={onRelancer} disabled={enCours} className="text-[12.5px] text-accent-text hover:underline disabled:opacity-50">
            Relancer
          </button>
        )}
        {peutAnnuler && (
          <button onClick={onAnnuler} disabled={enCours} className="text-[12.5px] text-danger hover:underline disabled:opacity-50">
            Annuler
          </button>
        )}
      </div>
      {message && <p className={`text-[11.5px] ${message.erreur ? "text-danger" : "text-ink-dim"}`}>{message.texte}</p>}
    </div>
  );
}
