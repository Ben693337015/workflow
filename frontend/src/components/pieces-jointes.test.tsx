import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const deposerMock = vi.fn();
const telechargerMock = vi.fn();
const enregistrerMock = vi.fn();
vi.mock("@/lib/telechargement", () => ({ enregistrerFichier: (...a: unknown[]) => enregistrerMock(...a) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    deposerPieceJointe: (...a: unknown[]) => deposerMock(...a),
    telechargerPieceJointe: (...a: unknown[]) => telechargerMock(...a),
  };
});

import { PiecesJointes } from "./pieces-jointes";

const pieces = [
  { id: "p1", nom: "recu-taxi.pdf", categorie: "recu" },
  { id: "p2", nom: "annexe.pdf", categorie: "complement" },
];

beforeEach(() => vi.clearAllMocks());

describe("PiecesJointes", () => {
  it("affiche chaque pièce et la télécharge sous son nom", async () => {
    telechargerMock.mockResolvedValue(new Blob(["contenu"]));
    render(<PiecesJointes demandeId="d1" pieces={pieces} />);

    await userEvent.click(screen.getByRole("button", { name: /recu-taxi\.pdf/ }));

    await waitFor(() => expect(telechargerMock).toHaveBeenCalledWith("d1", "p1"));
    expect(enregistrerMock).toHaveBeenCalledWith(expect.any(Blob), "recu-taxi.pdf");
    expect(screen.getByRole("button", { name: /recu-taxi\.pdf/ })).toHaveAttribute("title", "Reçu");
  });

  it("mode consultation (approbateur) : aucun champ de dépôt", () => {
    render(<PiecesJointes demandeId="d1" pieces={pieces} />);
    expect(screen.queryByLabelText(/ajouter une pièce/i)).not.toBeInTheDocument();
  });

  it("dépose une pièce sur la bonne demande puis prévient le parent", async () => {
    deposerMock.mockResolvedValue({ id: "p3", nom: "ticket.pdf", categorie: "recu" });
    const onAjoutee = vi.fn();
    render(<PiecesJointes demandeId="d1" pieces={[]} peutAjouter onAjoutee={onAjoutee} />);

    const fichier = new File(["%PDF"], "ticket.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/ajouter une pièce/i), fichier);

    await waitFor(() => expect(deposerMock).toHaveBeenCalledWith("d1", fichier));
    expect(onAjoutee).toHaveBeenCalledTimes(1);
  });

  it("affiche l'erreur du backend (ex. type refusé) et ne prévient pas le parent", async () => {
    const { ApiError } = await import("@/lib/api");
    deposerMock.mockRejectedValue(new ApiError(422, "Format de fichier non accepté (PDF, Word, PNG ou JPEG uniquement)."));
    const onAjoutee = vi.fn();
    render(<PiecesJointes demandeId="d1" pieces={[]} peutAjouter onAjoutee={onAjoutee} />);

    await userEvent.upload(screen.getByLabelText(/ajouter une pièce/i), new File(["MZ"], "v.exe", { type: "application/pdf" }));

    expect(await screen.findByText(/format de fichier non accepté/i)).toBeInTheDocument();
    expect(onAjoutee).not.toHaveBeenCalled();
  });

  it("affiche l'erreur d'un téléchargement refusé (403)", async () => {
    const { ApiError } = await import("@/lib/api");
    telechargerMock.mockRejectedValue(new ApiError(403, "Accès refusé à ces pièces."));
    render(<PiecesJointes demandeId="d1" pieces={pieces} />);

    await userEvent.click(screen.getByRole("button", { name: /annexe\.pdf/ }));

    expect(await screen.findByText(/accès refusé à ces pièces/i)).toBeInTheDocument();
    expect(enregistrerMock).not.toHaveBeenCalled();
  });
});
