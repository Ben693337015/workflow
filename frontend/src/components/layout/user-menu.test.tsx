import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { UserMenu } from "@/components/layout/user-menu";

// Polyfills necessaires : Radix UI (via Radix Popper/Presence) s'appuie sur
// des API Pointer Events que jsdom n'implemente pas completement.
beforeAll(() => {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
  Element.prototype.setPointerCapture = Element.prototype.setPointerCapture ?? (() => {});
  Element.prototype.releasePointerCapture = Element.prototype.releasePointerCapture ?? (() => {});
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
});

const utilisateur = {
  nom_complet: "ABDOULMADJID YAHYA",
  email: "abdoulmadjidyahya70@gmail.com",
  role: "drh",
};

describe("UserMenu (dropdown profil)", () => {
  it("affiche les initiales, le nom et le role dans le declencheur", () => {
    render(<UserMenu utilisateur={utilisateur} onDeconnexion={() => {}} />);
    expect(screen.getByText("AY")).toBeInTheDocument();
    expect(screen.getByText("ABDOULMADJID YAHYA")).toBeInTheDocument();
    expect(screen.getByText("DRH")).toBeInTheDocument();
  });

  it("le menu est ferme par defaut (email et Deconnexion absents du DOM)", () => {
    render(<UserMenu utilisateur={utilisateur} onDeconnexion={() => {}} />);
    expect(screen.queryByText("abdoulmadjidyahya70@gmail.com")).not.toBeInTheDocument();
    expect(screen.queryByText("Déconnexion")).not.toBeInTheDocument();
  });

  it("un clic sur le declencheur ouvre le menu (email + Deconnexion visibles)", async () => {
    render(<UserMenu utilisateur={utilisateur} onDeconnexion={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /menu du profil/i }));

    await waitFor(() => {
      expect(screen.getByText("abdoulmadjidyahya70@gmail.com")).toBeInTheDocument();
    });
    expect(screen.getByText("Déconnexion")).toBeInTheDocument();
    expect(screen.getByText("Mon profil")).toBeInTheDocument();
  });

  it("cliquer sur Deconnexion appelle bien onDeconnexion", async () => {
    const onDeconnexion = vi.fn();
    render(<UserMenu utilisateur={utilisateur} onDeconnexion={onDeconnexion} />);
    await userEvent.click(screen.getByRole("button", { name: /menu du profil/i }));

    const itemDeconnexion = await screen.findByText("Déconnexion");
    await userEvent.click(itemDeconnexion);

    expect(onDeconnexion).toHaveBeenCalledTimes(1);
  });

  it("l'item Deconnexion et l'icone partagent la meme grille d'alignement que Mon profil", async () => {
    render(<UserMenu utilisateur={utilisateur} onDeconnexion={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /menu du profil/i }));

    const itemProfil = await screen.findByText("Mon profil");
    const itemDeconnexion = await screen.findByText("Déconnexion");

    // Les deux items doivent porter la meme classe de grille
    // (grid-cols-[18px_1fr]) garantissant l'alignement icone/texte.
    const rowProfil = itemProfil.closest('[role="menuitem"]');
    const rowDeconnexion = itemDeconnexion.closest('[role="menuitem"]');
    expect(rowProfil?.className).toContain("grid-cols-[18px_1fr]");
    expect(rowDeconnexion?.className).toContain("grid-cols-[18px_1fr]");
  });
});
