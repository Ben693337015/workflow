import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** Pastille de marque : un « valide » dans un carré arrondi, l'action centrale du produit. */
export function Marque({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-strong text-white", className)}
    >
      <Check className="h-4 w-4" strokeWidth={2.75} />
    </span>
  );
}
