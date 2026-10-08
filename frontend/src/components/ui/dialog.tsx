"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

/**
 * Boite de dialogue centree dans la FENETRE (position fixe) : toujours visible, quel que soit l'endroit ou
 * l'on a defile. Radix fournit l'accessibilite : focus pris puis rendu, Echap, clic sur le fond, aria-modal.
 */
export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/40" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 flex max-h-[min(88dvh,46rem)] w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 flex-col",
          "overflow-hidden rounded-xl border border-line bg-surface shadow-[0_20px_60px_-10px_rgba(18,21,28,0.35)] outline-none",
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          aria-label="Fermer"
          className="absolute right-3 top-3 rounded-md p-1.5 text-ink-dim transition-colors hover:bg-canvas hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
        >
          <X className="h-4 w-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
