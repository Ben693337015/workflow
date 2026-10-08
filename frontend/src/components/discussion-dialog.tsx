"use client";

import * as React from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { DiscussionPanel } from "@/components/discussion-panel";
import { useAuth } from "@/hooks/useAuth";

/** Rendu seulement a l'ouverture : un dialogue ferme n'exige aucun contexte d'authentification. */
function PanneauDuDemandeur({ demandeId }: { demandeId: string }) {
  const { utilisateur } = useAuth();
  return <DiscussionPanel demandeId={demandeId} utilisateurId={utilisateur?.id} />;
}

/**
 * Discussion du DEMANDEUR avec l'approbateur, dans une boite de dialogue centree dans la fenetre.
 * Avant : panneau en bas de page, hors ecran apres le clic (mesure : y = 796 px pour une fenetre de 679 px),
 * sans rappel de la demande concernee. `demandeId` a null = fermee.
 */
export function DiscussionDialog({
  demandeId,
  titre,
  onClose,
}: {
  demandeId: string | null;
  titre: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={demandeId !== null} onOpenChange={(ouvert) => !ouvert && onClose()}>
      <DialogContent>
        <div className="shrink-0 border-b border-line px-6 py-4 pr-12">
          <DialogTitle className="text-[15px] font-semibold text-ink">Précisions demandées</DialogTitle>
          <DialogDescription className="mt-0.5 text-[13px] text-ink-dim">
            {titre}. Répondez à l&apos;approbateur : il reprendra ensuite sa décision.
          </DialogDescription>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {demandeId && <PanneauDuDemandeur demandeId={demandeId} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}
