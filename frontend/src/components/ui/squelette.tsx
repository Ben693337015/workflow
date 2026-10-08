import { cn } from "@/lib/utils";

/**
 * Squelette de chargement d'une liste ou d'un tableau : la forme du contenu à venir plutôt qu'un texte seul.
 * Le texte « Chargement… » reste présent pour les lecteurs d'écran (role="status"). L'animation est coupée
 * quand l'utilisateur demande moins de mouvement.
 */
export function SqueletteListe({ lignes = 3, className }: { lignes?: number; className?: string }) {
  return (
    <div role="status" className={cn("flex flex-col gap-3", className)}>
      <span className="sr-only">Chargement…</span>
      {Array.from({ length: lignes }, (_, i) => (
        <div key={i} aria-hidden="true" className="flex items-center gap-4">
          <div className="h-3.5 w-1/4 animate-pulse rounded bg-line motion-reduce:animate-none" />
          <div className="h-3.5 flex-1 animate-pulse rounded bg-line motion-reduce:animate-none" />
          <div className="h-3.5 w-16 animate-pulse rounded bg-line motion-reduce:animate-none" />
        </div>
      ))}
    </div>
  );
}
