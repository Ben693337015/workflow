import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { ActionsDemande } from "./actions-demande";
import { ApiError } from "@/lib/api";

const annuler = vi.fn();
const relancer = vi.fn();
const onChange = vi.fn();

beforeEach(() => vi.clearAllMocks());

describe("ActionsDemande", () => {
  it("n'affiche ni bouton ni rien quand aucune action n'est possible", () => {
    const { container } = render(
      <ActionsDemande demandeId="d1" peutAnnuler={false} peutRelancer={false} annuler={annuler} relancer={relancer} onChange={onChange} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("n'affiche que le bouton autorisé", () => {
    render(<ActionsDemande demandeId="d1" peutAnnuler={false} peutRelancer={true} annuler={annuler} relancer={relancer} onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Relancer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument();
  });

  it("annule puis prévient le parent (rechargement)", async () => {
    annuler.mockResolvedValue({ id: "d1", statut_global: "annulee" });
    render(<ActionsDemande demandeId="d1" peutAnnuler peutRelancer={false} annuler={annuler} relancer={relancer} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));

    await waitFor(() => expect(annuler).toHaveBeenCalledWith("d1"));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("échec de l'annulation : message affiché, pas de rechargement", async () => {
    annuler.mockRejectedValue(new ApiError(409, "Seule une demande encore en cours peut être annulée."));
    render(<ActionsDemande demandeId="d1" peutAnnuler peutRelancer={false} annuler={annuler} relancer={relancer} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));

    expect(await screen.findByText(/seule une demande encore en cours/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("relance réussie : le message du backend s'affiche, sans recharger la liste", async () => {
    relancer.mockResolvedValue({ id: "d1", email_envoye: true, detail: "Notification renvoyée à l'approbateur." });
    render(<ActionsDemande demandeId="d1" peutAnnuler={false} peutRelancer annuler={annuler} relancer={relancer} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Relancer" }));

    expect(await screen.findByText("Notification renvoyée à l'approbateur.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled(); // rien ne change dans la liste : le statut reste "en_cours"
  });

  it("relance avec échec d'envoi (200 mais email_envoye=false) : message affiché en rouge", async () => {
    relancer.mockResolvedValue({ id: "d1", email_envoye: false, detail: "L'e-mail n'a pas pu être envoyé." });
    render(<ActionsDemande demandeId="d1" peutAnnuler={false} peutRelancer annuler={annuler} relancer={relancer} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Relancer" }));

    const message = await screen.findByText("L'e-mail n'a pas pu être envoyé.");
    expect(message).toHaveClass("text-danger");
  });

  it("échec réseau de la relance (exception) : message générique affiché", async () => {
    relancer.mockRejectedValue(new ApiError(409, "Cette demande n'attend plus de décision."));
    render(<ActionsDemande demandeId="d1" peutAnnuler={false} peutRelancer annuler={annuler} relancer={relancer} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Relancer" }));

    expect(await screen.findByText("Cette demande n'attend plus de décision.")).toBeInTheDocument();
  });

  it("un nouveau clic efface le message précédent", async () => {
    relancer.mockResolvedValueOnce({ id: "d1", email_envoye: true, detail: "Premier message." });
    render(<ActionsDemande demandeId="d1" peutAnnuler={false} peutRelancer annuler={annuler} relancer={relancer} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Relancer" }));
    await screen.findByText("Premier message.");

    relancer.mockResolvedValueOnce({ id: "d1", email_envoye: true, detail: "Second message." });
    await userEvent.click(screen.getByRole("button", { name: "Relancer" }));

    expect(await screen.findByText("Second message.")).toBeInTheDocument();
    expect(screen.queryByText("Premier message.")).not.toBeInTheDocument();
  });
});
