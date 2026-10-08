import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

const historiqueMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, historiqueDemande: (...a: unknown[]) => historiqueMock(...a) };
});

import { HistoriqueDossier } from "./historique-dossier";

beforeEach(() => vi.clearAllMocks());

describe("HistoriqueDossier", () => {
  it("affiche la chronologie : libellé, auteur et détail, dans l'ordre reçu", async () => {
    historiqueMock.mockResolvedValue([
      { horodate_le: "2026-06-01T10:00:00Z", action: "demande_soumise", libelle: "Demande soumise", acteur_nom: "Eric Employe", detail: null },
      { horodate_le: "2026-06-02T09:00:00Z", action: "etape_approuvee", libelle: "Étape approuvée", acteur_nom: "Marie Manager", detail: "Commentaire : OK pour moi" },
    ]);
    render(<HistoriqueDossier demandeId="d1" />);

    expect(await screen.findByText(/historique du dossier \(2\)/i)).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Demande soumise — Eric Employe");
    expect(items[1]).toHaveTextContent("Étape approuvée — Marie Manager");
    expect(items[1]).toHaveTextContent("Commentaire : OK pour moi");
    expect(historiqueMock).toHaveBeenCalledWith("d1");
  });

  it("n'affiche rien pour un historique vide", async () => {
    historiqueMock.mockResolvedValue([]);
    const { container } = render(<HistoriqueDossier demandeId="d1" />);
    await waitFor(() => expect(historiqueMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("reste silencieux si l'accès est refusé : c'est une aide à la décision, jamais un prérequis", async () => {
    const { ApiError } = await import("@/lib/api");
    historiqueMock.mockRejectedValue(new ApiError(403, "Accès refusé à cet historique."));
    const { container } = render(<HistoriqueDossier demandeId="d1" />);
    await waitFor(() => expect(historiqueMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
