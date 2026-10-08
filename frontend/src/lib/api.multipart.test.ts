import { describe, it, expect, vi, beforeEach } from "vitest";
import { deposerPieceJointe, envoyerMessageAvecFichier, soumettreDemandeAchat } from "./api";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

beforeEach(() => {
  fetchMock.mockReset();
  localStorage.clear();
});

describe("soumettreDemandeAchat (multipart)", () => {
  it("envoie un FormData sans Content-Type explicite (le navigateur ajoute la frontiere) et sans jeton lisible", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: "a1", statut_global: "en_cours", premiere_etape_id: "e", derogation: true }), {
        status: 201,
      })
    );
    const fichier = new File(["%PDF"], "contrat.pdf", { type: "application/pdf" });

    const resultat = await soumettreDemandeAchat({
      tiers: "X",
      objet: "Y",
      budget_engage: 99.5,
      derogation_motivee: true,
      motif_derogation: "Urgent",
      fichier_contrat: fichier,
    });

    expect(resultat.derogation).toBe(true);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/backend/api/v1/achats/");
    expect(options.method).toBe("POST");
    // R23 : aucun en-tete Authorization cote navigateur, la session voyage dans un cookie httpOnly.
    expect(options.headers).toEqual({});
    expect(options.headers["Content-Type"]).toBeUndefined();
    const corps = options.body as FormData;
    expect(corps).toBeInstanceOf(FormData);
    expect(corps.get("budget_engage")).toBe("99.5");
    expect(corps.get("derogation_motivee")).toBe("true");
    expect(corps.get("motif_derogation")).toBe("Urgent");
    expect((corps.get("fichier_contrat") as File).name).toBe("contrat.pdf");
  });

  it("n'envoie pas de motif quand la dérogation n'est pas demandée, et remonte le détail d'erreur du backend", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Le fichier du contrat est vide." }), { status: 422 })
    );

    await expect(
      soumettreDemandeAchat({
        tiers: "X",
        objet: "Y",
        budget_engage: 1,
        derogation_motivee: false,
        motif_derogation: "ignoré",
        fichier_contrat: new File([""], "v.pdf"),
      })
    ).rejects.toThrow("Le fichier du contrat est vide.");

    const corps = fetchMock.mock.calls[0][1].body as FormData;
    expect(corps.has("motif_derogation")).toBe(false);
  });
});

describe("envoyerMessageAvecFichier (multipart)", () => {
  it("envoie contenu + fichier vers la route dédiée, sans Content-Type explicite", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: "m1", fichier_nom: "j.pdf" }), { status: 201 })
    );
    const fichier = new File(["%PDF"], "j.pdf", { type: "application/pdf" });

    await envoyerMessageAvecFichier("d1", "Voici la pièce.", fichier);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/backend/api/v1/demandes/d1/messages/avec-fichier");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBeUndefined();
    const corps = options.body as FormData;
    expect(corps.get("contenu")).toBe("Voici la pièce.");
    expect((corps.get("fichier") as File).name).toBe("j.pdf");
  });
});

describe("deposerPieceJointe (multipart)", () => {
  it("envoie le seul champ fichier vers la route de la demande - la catégorie n'est jamais choisie par le client", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: "p1", nom: "r.pdf", categorie: "recu" }), { status: 201 }));
    const fichier = new File(["%PDF"], "r.pdf", { type: "application/pdf" });

    const piece = await deposerPieceJointe("d9", fichier);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/backend/api/v1/demandes/d9/pieces-jointes");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBeUndefined();
    const corps = options.body as FormData;
    expect([...corps.keys()]).toEqual(["fichier"]);
    expect(piece.categorie).toBe("recu");
  });
});
