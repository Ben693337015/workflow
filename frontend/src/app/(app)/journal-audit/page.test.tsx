import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

let roleCourant = "drh";
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ utilisateur: { id: "1", nom_complet: "Test", email: "t@t.tld", role: roleCourant }, connecte: true, chargement: false }),
}));

const journalMock = vi.fn();
const actionsMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    consulterJournal: (...a: unknown[]) => journalMock(...a),
    listerActionsAudit: (...a: unknown[]) => actionsMock(...a),
  };
});

import JournalAuditPage, { resumerDetails } from "./page";

const entree = (i: number, extra = {}) => ({
  id: `id-${i}-aaaaaaaa`, action: "compte_modifie", libelle: "Compte modifié", acteur_id: "u1", acteur_nom: "Aïcha Bello",
  cible_type: "utilisateur", cible_id: `cible-${i}-bbbbbbbb`, details: { email: "x@t.tld" }, horodate_le: "2026-06-01T10:00:00Z", ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  roleCourant = "drh";
  actionsMock.mockResolvedValue([
    { action: "compte_modifie", libelle: "Compte modifié" },
    { action: "etape_approuvee", libelle: "Étape approuvée" },
  ]);
  journalMock.mockResolvedValue({ total: 2, limit: 25, offset: 0, elements: [entree(1), entree(2, { acteur_nom: "Système", acteur_id: null })] });
});

describe("JournalAuditPage", () => {
  it("affiche chaque entrée : date, libellé français, auteur (Système pour une action automatique), cible et détails", async () => {
    render(<JournalAuditPage />);

    await screen.findByText("1–2 sur 2");
    // Le libelle figure aussi comme option du filtre : on ne compte que les cellules du tableau.
    expect(screen.getAllByRole("cell", { name: "Compte modifié" })).toHaveLength(2);
    expect(screen.getByText("Aïcha Bello")).toBeInTheDocument();
    expect(screen.getByText("Système")).toBeInTheDocument();
    expect(screen.getByText("utilisateur · cible-1-")).toBeInTheDocument();
    expect(screen.getAllByText("email : x@t.tld")).toHaveLength(2);
    expect(screen.getByText("1–2 sur 2")).toBeInTheDocument();
  });

  it.each(["drh", "direction_generale", "controleur_de_gestion"])("le rôle %s accède au journal", async (role) => {
    roleCourant = role;
    render(<JournalAuditPage />);
    expect(await screen.findAllByText("Compte modifié")).not.toHaveLength(0);
  });

  it.each(["employe", "manager", "service_juridique", "direction_financiere"])("le rôle %s voit un refus et aucun appel n'est fait", (role) => {
    roleCourant = role;
    render(<JournalAuditPage />);

    expect(screen.getByText(/réservé à la drh/i)).toBeInTheDocument();
    expect(journalMock).not.toHaveBeenCalled();
    expect(actionsMock).not.toHaveBeenCalled();
  });

  it("filtrer par action recharge depuis la première page avec le bon paramètre", async () => {
    render(<JournalAuditPage />);
    await screen.findAllByText("Compte modifié");

    await userEvent.selectOptions(screen.getByLabelText("Action"), "etape_approuvee");

    await waitFor(() =>
      expect(journalMock).toHaveBeenLastCalledWith({ action: "etape_approuvee", depuis: undefined, jusqu_a: undefined, limit: 25, offset: 0 })
    );
  });

  it("les dates deviennent des bornes de journée UTC (début 00:00, fin 23:59:59)", async () => {
    render(<JournalAuditPage />);
    await screen.findAllByText("Compte modifié");

    await userEvent.type(screen.getByLabelText("Du"), "2026-06-01");
    await userEvent.type(screen.getByLabelText("Au"), "2026-06-30");

    await waitFor(() =>
      expect(journalMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ depuis: "2026-06-01T00:00:00Z", jusqu_a: "2026-06-30T23:59:59.999Z" })
      )
    );
  });

  it("pagination : Suivant avance de 25, Précédent revient, et les boutons se désactivent aux bornes", async () => {
    journalMock.mockResolvedValue({ total: 60, limit: 25, offset: 0, elements: [entree(1)] });
    render(<JournalAuditPage />);
    await screen.findByText("1–25 sur 60");
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Suivant" }));
    await waitFor(() => expect(journalMock).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 })));

    await userEvent.click(screen.getByRole("button", { name: "Précédent" }));
    await waitFor(() => expect(journalMock).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 })));
  });

  it("le dernier passage désactive Suivant", async () => {
    journalMock.mockResolvedValue({ total: 25, limit: 25, offset: 0, elements: [entree(1)] });
    render(<JournalAuditPage />);
    await screen.findByText("1–25 sur 25");
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });

  it("aucune entrée : message clair ; erreur du backend : affichée", async () => {
    journalMock.mockResolvedValueOnce({ total: 0, limit: 25, offset: 0, elements: [] });
    const { unmount } = render(<JournalAuditPage />);
    expect(await screen.findByText(/aucune entrée pour ces critères/i)).toBeInTheDocument();
    unmount();

    const { ApiError } = await import("@/lib/api");
    journalMock.mockRejectedValueOnce(new ApiError(403, "Accès refusé."));
    render(<JournalAuditPage />);
    expect(await screen.findByText("Accès refusé.")).toBeInTheDocument();
  });
});

describe("resumerDetails", () => {
  it("montre avant → après pour une modification, et clé : valeur sinon", () => {
    expect(
      resumerDetails({ email: "x@t.tld", changements: { role: { avant: "employe", apres: "manager" }, service: { avant: "Ventes", apres: "Finance" } } })
    ).toBe("email : x@t.tld · changements (role : employe → manager, service : Ventes → Finance)");
    expect(resumerDetails({ budget_alloue_avant: null, budget_alloue_apres: 1000 })).toBe("budget_alloue_avant : null · budget_alloue_apres : 1000");
    expect(resumerDetails({})).toBe("");
  });
});
