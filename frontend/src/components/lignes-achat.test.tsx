import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { LignesAchat } from "./lignes-achat";
import type { LigneAchat } from "@/types";

const uneLigne: LigneAchat[] = [{ description: "", montant_ht: 0, taux_tva: 20 }];

describe("LignesAchat", () => {
  it("affiche les totaux HT et TTC calculés en direct", () => {
    const lignes: LigneAchat[] = [
      { description: "Materiel", montant_ht: 1000, taux_tva: 20 },
      { description: "Documentation", montant_ht: 50, taux_tva: 5.5 },
    ];
    render(<LignesAchat lignes={lignes} onChange={() => {}} devise="EUR" />);

    expect(screen.getByText(/total ht/i).parentElement).toHaveTextContent("1 050,00");
    expect(screen.getByText(/total ttc/i)).toBeInTheDocument();
  });

  it("modifier une ligne met à jour uniquement cette ligne", async () => {
    const onChange = vi.fn();
    const lignes: LigneAchat[] = [
      { description: "A", montant_ht: 10, taux_tva: 20 },
      { description: "B", montant_ht: 20, taux_tva: 20 },
    ];
    render(<LignesAchat lignes={lignes} onChange={onChange} devise="EUR" />);

    await userEvent.type(screen.getByDisplayValue("A"), "X");

    expect(onChange).toHaveBeenLastCalledWith([
      { description: "AX", montant_ht: 10, taux_tva: 20 },
      { description: "B", montant_ht: 20, taux_tva: 20 },
    ]);
  });

  it("ajouter une ligne ajoute une ligne vide avec 20 % de TVA par défaut", async () => {
    const onChange = vi.fn();
    render(<LignesAchat lignes={uneLigne} onChange={onChange} devise="EUR" />);

    await userEvent.click(screen.getByRole("button", { name: /ajouter une ligne/i }));

    expect(onChange).toHaveBeenCalledWith([...uneLigne, { description: "", montant_ht: 0, taux_tva: 20 }]);
  });

  it("retirer une ligne la supprime", async () => {
    const onChange = vi.fn();
    const lignes: LigneAchat[] = [
      { description: "A", montant_ht: 10, taux_tva: 20 },
      { description: "B", montant_ht: 20, taux_tva: 20 },
    ];
    render(<LignesAchat lignes={lignes} onChange={onChange} devise="EUR" />);

    await userEvent.click(screen.getByRole("button", { name: /retirer la ligne 2/i }));

    expect(onChange).toHaveBeenCalledWith([lignes[0]]);
  });

  it("la dernière ligne ne peut pas être retirée (bouton désactivé)", () => {
    render(<LignesAchat lignes={uneLigne} onChange={() => {}} devise="EUR" />);
    expect(screen.getByRole("button", { name: /retirer la ligne 1/i })).toBeDisabled();
  });

  it("une saisie non numérique dans le montant retombe sur 0, sans planter", async () => {
    const onChange = vi.fn();
    const lignes: LigneAchat[] = [{ description: "A", montant_ht: 10, taux_tva: 20 }];
    render(<LignesAchat lignes={lignes} onChange={onChange} devise="EUR" />);

    const champMontant = screen.getAllByRole("spinbutton")[0];
    await userEvent.clear(champMontant);

    expect(onChange).toHaveBeenLastCalledWith([{ description: "A", montant_ht: 0, taux_tva: 20 }]);
  });
});
