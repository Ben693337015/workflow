import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Zone de defilement horizontal d'un tableau.
 *
 * Pourquoi : `Card` masque ce qui depasse (`overflow-hidden`, necessaire pour les coins arrondis). Un
 * tableau plus large que son cadre y etait donc simplement COUPE (colonne « Actions » invisible, noms de
 * fichiers tronques). Enveloppe dans ce composant, il garde sa largeur naturelle et defile dans son
 * cadre quand l'ecran est trop etroit, au lieu de perdre des colonnes.
 */
export function TableScroll({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("defilement-ombre w-full overflow-x-auto", className)} {...props} />;
}
