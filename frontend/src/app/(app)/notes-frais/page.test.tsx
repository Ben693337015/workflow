import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
const soumettreMock = vi.fn();
const deposerMock = vi.fn();
const listerDevisesMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    soumettreNoteDeFrais: (...a: unknown[]) => soumettreMock(...a),
    deposerPieceJointe: (...a: unknown[]) => deposerMock(...a),
    listerDevises: (...a: unknown[]) => listerDevisesMock(...a),
  };
});

import NotesFraisPage from "./page";

async function remplirFormulaire() {
  await userEvent.type(screen.getByLabelText("Montant (EUR)"), "120.50");
  await userEvent.type(screen.getByLabelText("Catégorie"), "Transport");
  await userEvent.type(screen.getByLabelText("Date de la dépense"), "2026-03-01");
  await userEvent.type(screen.getByLabelText("Description"), "Billet de train");
}

beforeEach(() => {
  vi.clearAllMocks();
  // Une seule devise (EUR) : le selecteur de devise reste masque, comme avant cette fonctionnalite.
  listerDevisesMock.mockResolvedValue({ reference: "EUR", devises: [{ code: "EUR", taux: 1, date_effet: null }] });
});

describe("NotesFraisPage (formulaire seul)", () => {
  it("ne contient plus que le formulaire : aucune liste de notes", async () => {
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    expect(screen.queryByText(/mes notes de frais/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("soumet le bon payload (sans dérogation) puis renvoie vers « Mes demandes »", async () => {
    soumettreMock.mockResolvedValue({ id: "n2", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");

    await remplirFormulaire();
    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));

    await waitFor(() =>
      expect(soumettreMock).toHaveBeenCalledWith({
        montant: 120.5,
        categorie: "Transport",
        date_depense: "2026-03-01",
        description: "Billet de train",
        derogation_motivee: false,
        motif_derogation: undefined,
      })
    );
    expect(await screen.findByText(/votre manager a été notifié/i)).toBeInTheDocument();
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/mes-demandes?type=notes_frais"), { timeout: 3000 });
    expect(screen.getByRole("link", { name: /suivre ma note de frais/i })).toHaveAttribute("href", "/mes-demandes?type=notes_frais");
  });

  it("cocher la dérogation révèle le motif, obligatoire avant tout envoi", async () => {
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    await remplirFormulaire();

    expect(screen.queryByLabelText("Motif de la dérogation")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/demande de dérogation motivée/i));
    expect(screen.getByLabelText("Motif de la dérogation")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));
    expect(await screen.findByText(/un motif est obligatoire/i)).toBeInTheDocument();
    expect(soumettreMock).not.toHaveBeenCalled();
  });

  it("un budget insuffisant coche automatiquement la dérogation pour guider l'utilisateur", async () => {
    const { ApiError } = await import("@/lib/api");
    soumettreMock.mockRejectedValue(
      new ApiError(422, "Budget insuffisant pour le service « Ventes » - un motif de dérogation est obligatoire pour soumettre malgré tout.")
    );
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    await remplirFormulaire();

    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));

    expect(await screen.findByText(/budget insuffisant/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/demande de dérogation motivée/i)).toBeChecked();
    expect(screen.getByLabelText("Motif de la dérogation")).toBeInTheDocument();
  });

  it("le champ date de la dépense est plafonné à aujourd'hui (le backend refuse une date future)", async () => {
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");

    expect(screen.getByLabelText("Date de la dépense")).toHaveAttribute("max", new Date().toISOString().slice(0, 10));
  });

  it("le reçu est facultatif : sans fichier, la note part et aucun dépôt n'est tenté", async () => {
    soumettreMock.mockResolvedValue({ id: "n7", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    await remplirFormulaire();

    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));

    await screen.findByText(/votre manager a été notifié/i);
    expect(deposerMock).not.toHaveBeenCalled();
  });

  it("avec un reçu : il est déposé sur la note qui vient d'être créée", async () => {
    soumettreMock.mockResolvedValue({ id: "n8", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    deposerMock.mockResolvedValue({ id: "p1", nom: "recu.pdf", categorie: "recu" });
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    await remplirFormulaire();
    const recu = new File(["%PDF"], "recu.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/reçu \(facultatif\)/i), recu);

    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));

    await waitFor(() => expect(deposerMock).toHaveBeenCalledWith("n8", recu));
    expect(await screen.findByText(/votre manager a été notifié/i)).toBeInTheDocument();
  });

  it("un reçu de plus de 40 Mo est refusé AVANT la création de la note (pas de note orpheline)", async () => {
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    await remplirFormulaire();
    const enorme = new File(["x"], "enorme.pdf", { type: "application/pdf" });
    Object.defineProperty(enorme, "size", { value: 40 * 1024 * 1024 + 1 });
    await userEvent.upload(screen.getByLabelText(/reçu \(facultatif\)/i), enorme);

    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));

    expect(await screen.findByText("Le fichier dépasse la taille maximale autorisée (40 Mo).")).toBeInTheDocument();
    expect(soumettreMock).not.toHaveBeenCalled();
    expect(deposerMock).not.toHaveBeenCalled();
  });

  it("un échec d'envoi du reçu n'annule pas la note : succès conservé et avertissement clair", async () => {
    const { ApiError } = await import("@/lib/api");
    soumettreMock.mockResolvedValue({ id: "n9", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    deposerMock.mockRejectedValue(new ApiError(422, "Le fichier dépasse la taille maximale autorisée (40 Mo)."));
    render(<NotesFraisPage />);
    await screen.findByLabelText("Catégorie");
    await remplirFormulaire();
    await userEvent.upload(screen.getByLabelText(/reçu \(facultatif\)/i), new File(["x"], "gros.pdf", { type: "application/pdf" }));

    await userEvent.click(screen.getByRole("button", { name: /soumettre la note de frais/i }));

    expect(await screen.findByText(/le reçu n'a pas pu être envoyé/i)).toBeInTheDocument();
    expect(screen.getByText(/dépasse la taille maximale/i)).toBeInTheDocument();
    expect(screen.getByText(/votre manager a été notifié/i)).toBeInTheDocument(); // la note, elle, est bien partie
    expect(screen.queryByText(/une erreur est survenue/i)).not.toBeInTheDocument(); // pas d'erreur bloquante
    expect(screen.getByText(/depuis « mes demandes »/i)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 1500));
    expect(pushMock).not.toHaveBeenCalled(); // l'avertissement reste lisible : pas de redirection
  });
});
