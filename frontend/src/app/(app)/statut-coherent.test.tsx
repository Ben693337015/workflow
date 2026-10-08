import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { STYLE_STATUT, statutDe } from "@/lib/demandes";

/**
 * Un meme statut doit porter le meme libelle pour les trois circuits. Ecart constate (05/10) :
 * « Complément demandé » (conges) contre « Précisions demandées » (notes de frais et achats).
 * Depuis le regroupement dans « Mes demandes » (07/10), les libelles ont UNE seule source (lib/demandes.ts) :
 * les pages-formulaires n'en definissent plus aucun.
 */
describe("libellé du statut « complement_demande »", () => {
  it("reprend le terme de la boîte de dialogue (« Précisions demandées »)", () => {
    expect(STYLE_STATUT.complement_demande.label).toBe("Précisions demandées");
  });

  it("est identique pour les congés, les notes de frais et les achats", () => {
    const libelle = (type: "conges" | "notes_frais" | "achats") =>
      statutDe({ type, demande: { id: "x", statut_global: "complement_demande", donnees: {} } } as never).label;
    expect(new Set(["conges", "notes_frais", "achats"].map((t) => libelle(t as never))).size).toBe(1);
  });

  it("un achat terminé est « Signé », pas « Approuvé »", () => {
    const l = (type: "conges" | "achats") => statutDe({ type, demande: { id: "x", statut_global: "terminee", donnees: {} } } as never).label;
    expect(l("achats")).toBe("Signée");
    expect(l("conges")).toBe("Approuvée");
  });

  it("les pages-formulaires ne redéfinissent aucun statut", () => {
    for (const page of ["notes-frais", "achats"]) {
      const source = readFileSync(join(__dirname, page, "page.tsx"), "utf-8");
      expect(source).not.toMatch(/complement_demande/);
    }
  });
});
