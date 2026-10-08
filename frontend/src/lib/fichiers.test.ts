import { describe, it, expect } from "vitest";
import { TAILLE_MAX_FICHIER_MO, TAILLE_MAX_FICHIER_OCTETS, messageTailleFichier } from "./fichiers";

/** Faux fichier de taille donnee, sans allouer la memoire (File.size est en lecture seule : on la surcharge). */
function fichierDe(octets: number): File {
  const f = new File(["x"], "gros.pdf", { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: octets });
  return f;
}

const MO = 1024 * 1024;

describe("messageTailleFichier", () => {
  it("la limite est de 40 Mo (valeurs littérales : un changement accidentel doit se voir)", () => {
    expect(TAILLE_MAX_FICHIER_MO).toBe(40);
    expect(TAILLE_MAX_FICHIER_OCTETS).toBe(40 * MO);
  });

  it("accepte l'absence de fichier et les fichiers jusqu'à 40 Mo inclus (30 Mo + 1 était refusé avant)", () => {
    expect(messageTailleFichier(null)).toBeNull();
    expect(messageTailleFichier(undefined)).toBeNull();
    for (const taille of [1, 10 * MO + 1, 12 * MO, 29 * MO, 30 * MO, 30 * MO + 1, 39 * MO, 40 * MO]) {
      expect(messageTailleFichier(fichierDe(taille))).toBeNull();
    }
  });

  it("refuse 40 Mo + 1 octet, avec le même message que le serveur", () => {
    expect(messageTailleFichier(fichierDe(40 * MO + 1))).toBe("Le fichier dépasse la taille maximale autorisée (40 Mo).");
  });
});
