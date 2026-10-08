import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

let roleCourant = "drh";
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ utilisateur: { id: "1", nom_complet: "Test", email: "t@t.tld", role: roleCourant }, connecte: true, chargement: false }),
}));

const syntheseMock = vi.fn();
const exportMock = vi.fn();
const enregistrerMock = vi.fn();
vi.mock("@/lib/telechargement", () => ({ enregistrerFichier: (...a: unknown[]) => enregistrerMock(...a) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, syntheseNotesDeFrais: (...a: unknown[]) => syntheseMock(...a), exporterSyntheseCsv: (...a: unknown[]) => exportMock(...a) };
});

import SyntheseFraisPage from "./page";

const ligne = (i: number, extra = {}) => ({
  id: `n${i}`, valide_le: "2026-06-01T10:00:00Z", demandeur_nom: "Eric Employe", service: "Ventes", categorie: "Repas",
  date_depense: "2026-03-01", description: "x", montant: 80, devise: "EUR", taux_applique: 1, montant_reference: 80,
  valide_par: ["Marie Manager"], derogation: false, nb_pieces: 1, ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  roleCourant = "drh";
  syntheseMock.mockResolvedValue({
    devise_reference: "EUR", nombre: 1, total_reference: 80, total_lignes: 1, limit: 25, offset: 0, tronque: false,
    par_devise: [{ devise: "EUR", nombre: 1, total: 80, total_reference: 80 }], elements: [ligne(1)],
  });
});

describe("SyntheseFraisPage", () => {
  it("affiche une ligne avec demandeur, montant, validateur et pièces", async () => {
    render(<SyntheseFraisPage />);

    expect(await screen.findByText("Eric Employe")).toBeInTheDocument();
    expect(screen.getByText("Marie Manager")).toBeInTheDocument();
    expect(screen.getByText("80,00 €")).toBeInTheDocument();
    expect(screen.getByText("1–1 sur 1")).toBeInTheDocument();
  });

  it("montre l'équivalent quand la devise diffère de la référence, et le signale par un badge de dérogation", async () => {
    syntheseMock.mockResolvedValue({
      devise_reference: "EUR", nombre: 1, total_reference: 73.6, total_lignes: 1, limit: 25, offset: 0, tronque: false,
      par_devise: [{ devise: "USD", nombre: 1, total: 80, total_reference: 73.6 }],
      elements: [ligne(1, { devise: "USD", montant_reference: 73.6, derogation: true })],
    });
    render(<SyntheseFraisPage />);

    expect(await screen.findByText(/80,00 \$US.*≈.*73,60 €/)).toBeInTheDocument();
    expect(screen.getByText("Dérogation")).toBeInTheDocument();
    expect(screen.getByText((_, el) => el?.textContent === "1 en USD (≈ 73.6 EUR)")).toBeInTheDocument();
  });

  it.each(["drh", "direction_financiere", "controleur_de_gestion"])("le rôle %s accède à l'écran", async (role) => {
    roleCourant = role;
    render(<SyntheseFraisPage />);
    expect(await screen.findByText("Eric Employe")).toBeInTheDocument();
  });

  it.each(["employe", "manager", "direction_generale", "service_juridique"])("le rôle %s voit un refus, aucun appel", (role) => {
    roleCourant = role;
    render(<SyntheseFraisPage />);
    expect(screen.getByText(/réservée à la drh/i)).toBeInTheDocument();
    expect(syntheseMock).not.toHaveBeenCalled();
  });

  it("filtrer par service recharge depuis la première page", async () => {
    render(<SyntheseFraisPage />);
    await screen.findByText("Eric Employe");

    await userEvent.type(screen.getByLabelText("Service"), "Finance");

    await waitFor(() =>
      expect(syntheseMock).toHaveBeenLastCalledWith({ depuis: undefined, jusqu_a: undefined, service: "Finance", limit: 25, offset: 0 })
    );
  });

  it("exporte en CSV avec les mêmes filtres que l'écran", async () => {
    exportMock.mockResolvedValue(new Blob(["csv"]));
    render(<SyntheseFraisPage />);
    await screen.findByText("Eric Employe");
    await userEvent.type(screen.getByLabelText("Service"), "Ventes");

    await userEvent.click(screen.getByRole("button", { name: /exporter en csv/i }));

    await waitFor(() => expect(exportMock).toHaveBeenCalledWith({ depuis: undefined, jusqu_a: undefined, service: "Ventes" }));
    expect(enregistrerMock).toHaveBeenCalledWith(expect.any(Blob), expect.stringMatching(/^synthese-notes-de-frais-\d{4}-\d{2}-\d{2}\.csv$/));
  });

  it("échec de l'export : erreur affichée, aucun fichier enregistré", async () => {
    const { ApiError } = await import("@/lib/api");
    exportMock.mockRejectedValue(new ApiError(403, "Accès refusé."));
    render(<SyntheseFraisPage />);
    await screen.findByText("Eric Employe");

    await userEvent.click(screen.getByRole("button", { name: /exporter en csv/i }));

    expect(await screen.findByText("Accès refusé.")).toBeInTheDocument();
    expect(enregistrerMock).not.toHaveBeenCalled();
  });

  it("aucune note validée : message clair", async () => {
    syntheseMock.mockResolvedValue({ devise_reference: "EUR", nombre: 0, total_reference: 0, total_lignes: 0, limit: 25, offset: 0, tronque: false, par_devise: [], elements: [] });
    render(<SyntheseFraisPage />);
    expect(await screen.findByText(/aucune note de frais validée pour ces critères/i)).toBeInTheDocument();
  });
});
