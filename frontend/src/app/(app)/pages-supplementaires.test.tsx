import { describe, it, expect, beforeAll, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ jeton: "jeton-test-123" }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    connecte: true,
    chargement: false,
    utilisateur: { id: "1", nom_complet: "Test Manager", email: "m@test.tld", role: "manager" },
    seConnecter: vi.fn(),
    ouvrirSession: vi.fn(),
    seDeconnecter: vi.fn(),
  }),
}));

const listerMonEquipeMock = vi.fn();
const listerTypesCongeMock = vi.fn();
const regulariserDemandeCongesMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listerMonEquipe: (...args: unknown[]) => listerMonEquipeMock(...args),
    listerTypesConge: (...args: unknown[]) => listerTypesCongeMock(...args),
    regulariserDemandeConges: (...args: unknown[]) => regulariserDemandeCongesMock(...args),
  };
});

beforeAll(() => {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
});
import RegularisationPage from "@/app/(app)/regularisation/page";

describe("RegularisationPage", () => {
  it("exige un commentaire en cas de refus", async () => {
    listerMonEquipeMock.mockResolvedValue([
      { id: "u1", email: "a@test.tld", nom_complet: "Aïcha Bello" },
    ]);
    listerTypesCongeMock.mockResolvedValue([{ id: "t1", nom: "Congé payé" }]);
    render(<RegularisationPage />);
    await screen.findByLabelText("Employé");

    await userEvent.selectOptions(screen.getByLabelText("Décision"), "refuser");
    await userEvent.type(screen.getByLabelText("Date de début"), "2026-10-01");
    await userEvent.type(screen.getByLabelText("Date de fin"), "2026-10-02");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer la régularisation/i }));

    expect(
      await screen.findByText(/un commentaire est obligatoire en cas de refus/i)
    ).toBeInTheDocument();
    expect(regulariserDemandeCongesMock).not.toHaveBeenCalled();
  });
});
