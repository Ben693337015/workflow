import { describe, it, expect } from "vitest";
import { libelleRole } from "./roles";

describe("libelleRole", () => {
  it("affiche DRH en majuscules (acronyme), pas Drh", () => {
    expect(libelleRole("drh")).toBe("DRH");
  });

  it("donne un libellé lisible pour les 7 rôles, sans underscore", () => {
    const roles: Array<[string, string]> = [
      ["employe", "Employé"],
      ["manager", "Manager"],
      ["drh", "DRH"],
      ["direction_financiere", "Direction financière"],
      ["service_juridique", "Service juridique"],
      ["direction_generale", "Direction générale"],
      ["controleur_de_gestion", "Contrôleur de gestion"],
    ];
    for (const [role, attendu] of roles) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      expect(libelleRole(role as any)).toBe(attendu);
      expect(libelleRole(role as any)).not.toContain("_");
    }
  });
});
