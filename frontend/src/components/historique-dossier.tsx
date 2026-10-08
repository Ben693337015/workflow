"use client";

import * as React from "react";
import { historiqueDemande } from "@/lib/api";
import { formaterHorodatage } from "@/lib/dates";
import type { HistoriqueEntree } from "@/types";

/**
 * Chronologie d'un dossier : qui a fait quoi, et quand (CDC 2.4 : tracabilite). Un approbateur de
 * second niveau y voit ce que le premier a decide et pourquoi. Le contenu des messages de
 * discussion n'y figure pas (il a sa propre route). Silencieux si l'acces est refuse : ce n'est
 * qu'une aide a la decision, jamais un prerequis.
 */
export function HistoriqueDossier({ demandeId }: { demandeId: string }) {
  const [lignes, setLignes] = React.useState<HistoriqueEntree[] | null>(null);

  React.useEffect(() => {
    historiqueDemande(demandeId)
      .then(setLignes)
      .catch(() => setLignes(null));
  }, [demandeId]);

  if (!lignes || lignes.length === 0) return null;

  return (
    <details className="rounded-lg border border-line p-3 text-[13px]">
      <summary className="cursor-pointer font-medium text-ink">Historique du dossier ({lignes.length})</summary>
      <ol className="mt-2 flex flex-col gap-2" aria-label="Historique du dossier">
        {lignes.map((l, i) => (
          <li key={i} className="flex flex-col">
            <span className="text-[12px] text-ink-faint">{formaterHorodatage(l.horodate_le)}</span>
            <span className="text-ink">
              {l.libelle} — <span className="text-ink-dim">{l.acteur_nom}</span>
            </span>
            {l.detail && <span className="text-[12.5px] text-ink-dim">{l.detail}</span>}
          </li>
        ))}
      </ol>
    </details>
  );
}
