"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Champ de choix de fichier en français.
 *
 * Le contrôle natif `<input type="file">` affiche « Choose File / No file chosen » selon la langue du
 * navigateur, pas celle de la page. L'input réel reste dans le DOM (masqué visuellement, focalisable, avec son
 * id et son libellé) : le clavier, les lecteurs d'écran et les tests continuent de fonctionner ; seul l'habillage
 * visible change. Pour réinitialiser le champ, changer sa `key` comme avec un input ordinaire.
 */
export function ChampFichier({
  libelle = "Choisir un fichier",
  compact = false,
  className,
  onChange,
  ...props
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "children"> & { libelle?: string; compact?: boolean }) {
  const [nom, setNom] = React.useState<string | null>(null);
  return (
    <div className={cn("relative flex min-w-0 items-center gap-2", className)}>
      <input
        {...props}
        type="file"
        className="peer sr-only"
        onChange={(e) => {
          setNom(e.target.files?.[0]?.name ?? null);
          onChange?.(e);
        }}
      />
      <label
        htmlFor={props.id}
        className={cn(
          "inline-flex shrink-0 cursor-pointer items-center rounded-lg border border-line-strong bg-surface text-ink transition-colors duration-150 hover:bg-canvas",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-accent-strong peer-focus-visible:ring-offset-2 peer-disabled:pointer-events-none peer-disabled:opacity-50",
          compact ? "px-2 py-0.5 text-[11.5px]" : "px-3 py-1.5 text-[13px]"
        )}
      >
        {libelle}
      </label>
      <span className={cn("min-w-0 truncate text-ink-dim", compact ? "max-w-[7rem] text-[11.5px]" : "text-[13px]")} title={nom ?? undefined}>
        {nom ?? "Aucun fichier"}
      </span>
    </div>
  );
}
