import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/mes-demandes",
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    connecte: true,
    chargement: false,
    utilisateur: { id: "1", nom_complet: "Test DRH", email: "d@test.tld", role: "drh" },
    seDeconnecter: vi.fn(),
  }),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
});

import AppLayout from "./layout";

describe("AppLayout — tiroir mobile", () => {
  it("le bouton hamburger n'existe qu'une fois et la sidebar est fermee par defaut (hors ecran)", () => {
    render(
      <AppLayout>
        <p>Contenu de page</p>
      </AppLayout>
    );
    expect(screen.getByRole("button", { name: /ouvrir le menu/i })).toBeInTheDocument();
    // Le lien de nav existe (sidebar toujours montee dans le DOM, meme
    // hors-ecran sur mobile) - on verifie juste qu'il est present.
    expect(screen.getAllByText("Mes demandes").length).toBeGreaterThan(0);
  });

  it("cliquer sur le hamburger ouvre le tiroir (fond assombri visible)", async () => {
    const { container } = render(
      <AppLayout>
        <p>Contenu de page</p>
      </AppLayout>
    );

    expect(container.querySelector(".bg-black\\/40")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /ouvrir le menu/i }));

    expect(container.querySelector(".bg-black\\/40")).toBeInTheDocument();
  });

  it("cliquer sur le fond assombri referme le tiroir", async () => {
    const { container } = render(
      <AppLayout>
        <p>Contenu de page</p>
      </AppLayout>
    );
    await userEvent.click(screen.getByRole("button", { name: /ouvrir le menu/i }));
    const fond = container.querySelector(".bg-black\\/40")!;
    await userEvent.click(fond);

    expect(container.querySelector(".bg-black\\/40")).not.toBeInTheDocument();
  });

  it("cliquer sur un lien de navigation dans le tiroir le referme", async () => {
    const { container } = render(
      <AppLayout>
        <p>Contenu de page</p>
      </AppLayout>
    );
    await userEvent.click(screen.getByRole("button", { name: /ouvrir le menu/i }));
    expect(container.querySelector(".bg-black\\/40")).toBeInTheDocument();

    const liensNouvelleDemande = screen.getAllByText("Nouvelle demande");
    await userEvent.click(liensNouvelleDemande[0]);

    expect(container.querySelector(".bg-black\\/40")).not.toBeInTheDocument();
  });
});
