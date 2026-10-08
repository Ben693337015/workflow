import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const listerTypesCongeMock = vi.fn();
const soumettreDemandeCongesMock = vi.fn();
const deposerMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listerTypesConge: (...args: unknown[]) => listerTypesCongeMock(...args),
    soumettreDemandeConges: (...args: unknown[]) => soumettreDemandeCongesMock(...args),
    deposerPieceJointe: (...args: unknown[]) => deposerMock(...args),
  };
});

import NouvelleDemandePage from "./page";

const typesDemo = [
  { id: "t1", code: "CP", nom: "Congé payé", taux_acquisition_jours_mois: 2.08, actif: true },
];

describe("NouvelleDemandePage", () => {
  it("affiche une erreur si la date de fin precede la date de debut, sans soumettre", async () => {
    listerTypesCongeMock.mockResolvedValue(typesDemo);
    render(<NouvelleDemandePage />);
    await screen.findByText("Congé payé");

    await userEvent.type(screen.getByLabelText("Date de début"), "2026-10-10");
    await userEvent.type(screen.getByLabelText("Date de fin"), "2026-10-05");
    await userEvent.click(screen.getByRole("button", { name: /envoyer la demande/i }));

    expect(
      await screen.findByText(/la date de fin doit être postérieure/i)
    ).toBeInTheDocument();
    expect(soumettreDemandeCongesMock).not.toHaveBeenCalled();
  });

  it("soumission valide : message de succes puis redirection vers /mes-demandes", async () => {
    listerTypesCongeMock.mockResolvedValue(typesDemo);
    soumettreDemandeCongesMock.mockResolvedValue({
      id: "d1",
      statut_global: "en_cours",
      nombre_jours: 3,
      premiere_etape_id: "e1",
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<NouvelleDemandePage />);
    await screen.findByText("Congé payé");

    await userEvent.type(screen.getByLabelText("Date de début"), "2026-10-05");
    await userEvent.type(screen.getByLabelText("Date de fin"), "2026-10-10");
    await userEvent.click(screen.getByRole("button", { name: /envoyer la demande/i }));

    await waitFor(() => {
      expect(screen.getByText(/demande soumise avec succès/i)).toBeInTheDocument();
    });
    expect(soumettreDemandeCongesMock).toHaveBeenCalledWith({
      type_conge_id: "t1",
      date_debut: "2026-10-05",
      date_fin: "2026-10-10",
      commentaire: undefined,
    });

    await vi.advanceTimersByTimeAsync(1300);
    expect(pushMock).toHaveBeenCalledWith("/mes-demandes");
    vi.useRealTimers();
  });
});

describe("NouvelleDemandePage — justificatif d'absence facultatif", () => {
  async function preparer() {
    listerTypesCongeMock.mockResolvedValue(typesDemo);
    soumettreDemandeCongesMock.mockResolvedValue({ id: "d42", statut_global: "en_cours", nombre_jours: 2, premiere_etape_id: "e1" });
    pushMock.mockClear();
    deposerMock.mockReset();
    render(<NouvelleDemandePage />);
    await screen.findByText("Congé payé");
    await userEvent.type(screen.getByLabelText("Date de début"), "2026-10-05");
    await userEvent.type(screen.getByLabelText("Date de fin"), "2026-10-06");
  }

  it("témoin : sans échec de dépôt, la redirection vers « Mes demandes » est bien programmée (1,2 s)", async () => {
    await preparer();
    const espion = vi.spyOn(globalThis, "setTimeout");
    await userEvent.click(screen.getByRole("button", { name: /envoyer la demande/i }));

    await screen.findByText(/demande soumise avec succès/i);
    expect(espion.mock.calls.filter((appel) => appel[1] === 1200)).toHaveLength(1);
    espion.mockRestore();
  });

  it("le justificatif est déposé sur la demande créée", async () => {
    await preparer();
    deposerMock.mockResolvedValue({ id: "p1", nom: "certificat.pdf", categorie: "justificatif" });
    const fichier = new File(["%PDF"], "certificat.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/justificatif d'absence/i), fichier);

    await userEvent.click(screen.getByRole("button", { name: /envoyer la demande/i }));

    await waitFor(() => expect(deposerMock).toHaveBeenCalledWith("d42", fichier));
  });

  it("sans justificatif : aucun dépôt tenté", async () => {
    await preparer();
    await userEvent.click(screen.getByRole("button", { name: /envoyer la demande/i }));

    await screen.findByText(/demande soumise avec succès/i);
    expect(deposerMock).not.toHaveBeenCalled();
  });

  it("échec du dépôt : demande conservée, avertissement affiché et AUCUNE redirection qui le masquerait", async () => {
    await preparer();
    const { ApiError } = await import("@/lib/api");
    deposerMock.mockRejectedValue(new ApiError(422, "Le fichier est vide."));
    await userEvent.upload(screen.getByLabelText(/justificatif d'absence/i), new File([""], "vide.pdf", { type: "application/pdf" }));
    const espion = vi.spyOn(globalThis, "setTimeout");

    await userEvent.click(screen.getByRole("button", { name: /envoyer la demande/i }));

    expect(await screen.findByText(/le justificatif n'a pas pu être envoyé/i)).toBeInTheDocument();
    expect(screen.getByText(/le fichier est vide/i)).toBeInTheDocument();
    expect(screen.getByText(/demande soumise avec succès/i)).toBeInTheDocument();
    // Aucun minuteur de redirection (1,2 s) programme par CETTE soumission : l'avertissement reste lisible.
    expect(espion.mock.calls.filter((appel) => appel[1] === 1200)).toHaveLength(0);
    espion.mockRestore();
  });
});
