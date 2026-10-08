import type { DemandeAchat, DemandeConges, NoteFrais, StatutDemande } from "@/types";

/**
 * Les trois circuits du demandeur, regroupes dans l'ecran « Mes demandes ».
 * Source unique des libelles de type et de statut : les pages-formulaires n'en ont plus besoin.
 */
export type TypeDemande = "conges" | "notes_frais" | "achats";

export type LigneDemande =
  | { type: "conges"; demande: DemandeConges }
  | { type: "notes_frais"; demande: NoteFrais }
  | { type: "achats"; demande: DemandeAchat };

export const TYPES_DEMANDE: Record<TypeDemande, { label: string; pluriel: string; formulaire: string; lienFormulaire: string }> = {
  conges: { label: "Congé", pluriel: "Congés", formulaire: "/nouvelle-demande", lienFormulaire: "Poser un congé" },
  notes_frais: { label: "Note de frais", pluriel: "Notes de frais", formulaire: "/notes-frais", lienFormulaire: "Déclarer une note de frais" },
  achats: { label: "Achat", pluriel: "Achats", formulaire: "/achats", lienFormulaire: "Faire une demande d'achat" },
};

export const ORDRE_TYPES: TypeDemande[] = ["conges", "notes_frais", "achats"];

/** Libelles des statuts, identiques sur les trois circuits (sauf « Signée » : un achat est signe, pas approuve). */
export const STYLE_STATUT: Record<StatutDemande, { label: string; className: string }> = {
  en_cours: { label: "En cours", className: "bg-warn-soft text-warn" },
  terminee: { label: "Approuvée", className: "bg-accent-soft text-accent-ink" },
  refusee: { label: "Refusée", className: "bg-danger-soft text-danger" },
  complement_demande: { label: "Précisions demandées", className: "bg-warn-soft text-warn" },
  annulee: { label: "Annulée", className: "bg-canvas text-ink-faint" },
};

export function statutDe(ligne: LigneDemande): { label: string; className: string } {
  const base = STYLE_STATUT[ligne.demande.statut_global];
  return ligne.type === "achats" && ligne.demande.statut_global === "terminee" ? { ...base, label: "Signée" } : base;
}

/** Regroupe les trois listes en une seule, la plus recente d'abord (celles sans date a la fin, ordre conserve). */
export function fusionner(conges: DemandeConges[], notes: NoteFrais[], achats: DemandeAchat[]): LigneDemande[] {
  const lignes: LigneDemande[] = [
    ...conges.map((demande) => ({ type: "conges" as const, demande })),
    ...notes.map((demande) => ({ type: "notes_frais" as const, demande })),
    ...achats.map((demande) => ({ type: "achats" as const, demande })),
  ];
  const date = (l: LigneDemande) => (l.demande.creee_le ? Date.parse(l.demande.creee_le) : Number.NEGATIVE_INFINITY);
  return lignes
    .map((l, i) => ({ l, i }))
    .sort((a, b) => date(b.l) - date(a.l) || a.i - b.i)
    .map(({ l }) => l);
}

export function compter(lignes: LigneDemande[]): Record<TypeDemande | "toutes", number> {
  const total = { toutes: lignes.length, conges: 0, notes_frais: 0, achats: 0 };
  for (const l of lignes) total[l.type] += 1;
  return total;
}

/** Valeur de `?type=` de l'URL → filtre valide, sinon « toutes ». */
export function filtreDepuisUrl(valeur: string | null | undefined): TypeDemande | "toutes" {
  return valeur === "conges" || valeur === "notes_frais" || valeur === "achats" ? valeur : "toutes";
}
