import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
const soumettreMock = vi.fn();
const listerDevisesMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    soumettreDemandeAchat: (...a: unknown[]) => soumettreMock(...a),
    listerDevises: (...a: unknown[]) => listerDevisesMock(...a),
  };
});

import AchatsPage from "./page";

async function remplir(avecFichier = true) {
  await userEvent.type(screen.getByLabelText("Fournisseur / tiers"), "Fournisseur X");
  await userEvent.type(screen.getByLabelText(/budget engagé/i), "1200");
  await userEvent.type(screen.getByLabelText("Objet de la dépense"), "Licences");
  if (avecFichier) {
    const fichier = new File(["%PDF"], "contrat.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Fichier du contrat"), fichier);
  }
}

beforeEach(() => {
  listerDevisesMock.mockResolvedValue({ reference: "EUR", devises: [{ code: "EUR", taux: 1, date_effet: null }] });
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
});

describe("AchatsPage (formulaire seul)", () => {
  it("ne contient plus que le formulaire : aucune liste de demandes", async () => {
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    expect(screen.queryByText(/mes demandes d.achat/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("le contrat est obligatoire : aucun appel API sans fichier", async () => {
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    await remplir(false);

    await userEvent.click(screen.getByRole("button", { name: /soumettre la demande d'achat/i }));

    expect(await screen.findByText(/fichier du contrat est obligatoire/i)).toBeInTheDocument();
    expect(soumettreMock).not.toHaveBeenCalled();
  });

  it("soumet le fichier et les champs, puis renvoie vers « Mes demandes »", async () => {
    soumettreMock.mockResolvedValue({ id: "a1", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    await remplir();

    await userEvent.click(screen.getByRole("button", { name: /soumettre la demande d'achat/i }));

    await waitFor(() => expect(soumettreMock).toHaveBeenCalledTimes(1));
    const envoye = soumettreMock.mock.calls[0][0];
    expect(envoye).toMatchObject({
      tiers: "Fournisseur X",
      objet: "Licences",
      budget_engage: 1200,
      derogation_motivee: false,
    });
    expect(envoye.fichier_contrat).toBeInstanceOf(File);
    expect(envoye.fichier_contrat.name).toBe("contrat.pdf");
    expect(await screen.findByText(/service juridique a été notifié/i)).toBeInTheDocument();
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/mes-demandes?type=achats"), { timeout: 3000 });
    expect(screen.getByRole("link", { name: /suivre ma demande/i })).toHaveAttribute("href", "/mes-demandes?type=achats");
  });

  it("un budget insuffisant coche automatiquement la dérogation", async () => {
    const { ApiError } = await import("@/lib/api");
    soumettreMock.mockRejectedValue(
      new ApiError(422, "Budget insuffisant - un motif de dérogation est obligatoire pour soumettre malgré tout.")
    );
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    await remplir();

    await userEvent.click(screen.getByRole("button", { name: /soumettre la demande d'achat/i }));

    expect(await screen.findByText(/budget insuffisant/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/demande de dérogation motivée/i)).toBeChecked();
  });
});

describe("AchatsPage — détail par ligne (TVA différenciée)", () => {
  it("le champ Budget engagé est masqué en mode détail, et réapparaît en revenant au montant global", async () => {
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    expect(screen.getByLabelText(/budget engagé/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /détailler par ligne/i }));

    expect(screen.queryByLabelText(/budget engagé/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /revenir à un montant global/i }));

    expect(screen.getByLabelText(/budget engagé/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Description")).not.toBeInTheDocument();
  });

  it("soumission en mode détail : les lignes remplies sont envoyées, sans budget_engage", async () => {
    soumettreMock.mockResolvedValue({ id: "a9", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    await userEvent.type(screen.getByLabelText("Fournisseur / tiers"), "Fournisseur X");
    await userEvent.type(screen.getByLabelText("Objet de la dépense"), "Licences");
    await userEvent.upload(screen.getByLabelText("Fichier du contrat"), new File(["%PDF"], "c.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: /détailler par ligne/i }));
    await userEvent.type(screen.getByLabelText("Description"), "Ordinateur portable");
    await userEvent.type(screen.getByLabelText("Montant HT"), "1000");

    await userEvent.click(screen.getByRole("button", { name: /soumettre la demande d'achat/i }));

    await waitFor(() => expect(soumettreMock).toHaveBeenCalled());
    const appel = soumettreMock.mock.calls[0][0];
    expect(appel.budget_engage).toBeUndefined();
    expect(appel.lignes).toEqual([{ description: "Ordinateur portable", montant_ht: 1000, taux_tva: 20 }]);
  });

  it("une ligne sans description ou sans montant est ignorée à la soumission", async () => {
    soumettreMock.mockResolvedValue({ id: "a9", statut_global: "en_cours", premiere_etape_id: "e", derogation: false });
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    await userEvent.type(screen.getByLabelText("Fournisseur / tiers"), "Fournisseur X");
    await userEvent.type(screen.getByLabelText("Objet de la dépense"), "Licences");
    await userEvent.upload(screen.getByLabelText("Fichier du contrat"), new File(["%PDF"], "c.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: /détailler par ligne/i }));
    await userEvent.type(screen.getByLabelText("Description"), "Ligne valide");
    await userEvent.type(screen.getByLabelText("Montant HT"), "100");
    await userEvent.click(screen.getByRole("button", { name: /ajouter une ligne/i })); // 2e ligne, laissee vide

    await userEvent.click(screen.getByRole("button", { name: /soumettre la demande d'achat/i }));

    await waitFor(() => expect(soumettreMock).toHaveBeenCalled());
    expect(soumettreMock.mock.calls[0][0].lignes).toHaveLength(1);
  });

  it("aucune ligne remplie en mode détail : erreur affichée, aucun appel", async () => {
    render(<AchatsPage />);
    await screen.findByLabelText("Fournisseur / tiers");
    await userEvent.type(screen.getByLabelText("Fournisseur / tiers"), "Fournisseur X");
    await userEvent.type(screen.getByLabelText("Objet de la dépense"), "Licences");
    await userEvent.upload(screen.getByLabelText("Fichier du contrat"), new File(["%PDF"], "c.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: /détailler par ligne/i }));

    await userEvent.click(screen.getByRole("button", { name: /soumettre la demande d'achat/i }));

    expect(await screen.findByText(/au moins une ligne/i)).toBeInTheDocument();
    expect(soumettreMock).not.toHaveBeenCalled();
  });
});
