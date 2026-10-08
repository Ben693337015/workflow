/**
 * Defilement de la mise en page : la barre laterale et le bandeau restent FIXES, seule la zone de contenu
 * (<main>) defile. Avant, c'etait la fenetre qui defilait : la barre laterale remontait avec la page et sortait
 * de l'ecran (mesure en navigateur : -384 px apres un defilement de 384 px).
 *
 * Ces tests verifient la STRUCTURE (jsdom ne calcule aucune mise en page). Le comportement reel est verifie dans un
 * vrai navigateur par scripts/verification/audit_interface.py.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

let pathname = "/mes-demandes";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => pathname,
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    connecte: true,
    chargement: false,
    utilisateur: {
      id: "1",
      nom_complet: "Prenom Nom-De-Famille-Tres-Long-Qui-Pourrait-Deborder",
      email: "d@test.tld",
      role: "drh",
    },
    seDeconnecter: vi.fn(),
  }),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
});

const scrollToMock = vi.fn();
beforeEach(() => {
  pathname = "/mes-demandes";
  scrollToMock.mockReset();
  // jsdom n'implemente pas Element.scrollTo
  Element.prototype.scrollTo = scrollToMock as unknown as typeof Element.prototype.scrollTo;
});

import AppLayout from "./layout";
import { TableScroll } from "@/components/ui/table";

const rendre = () =>
  render(
    <AppLayout>
      <p>Contenu</p>
    </AppLayout>
  );

describe("AppLayout — seule la zone de contenu defile", () => {
  it("le cadre occupe la hauteur de l'ecran et ne defile jamais lui-meme", () => {
    const { container } = rendre();
    const cadre = container.firstElementChild as HTMLElement;
    expect(cadre).toHaveClass("h-dvh", "overflow-hidden");
    // L'ancienne version (min-h-dvh) laissait la page s'allonger et defiler avec la barre laterale.
    expect(cadre).not.toHaveClass("min-h-dvh");
  });

  it("<main> est le seul element qui defile verticalement", () => {
    rendre();
    const main = screen.getByRole("main");
    expect(main).toHaveClass("overflow-y-auto", "min-h-0", "flex-1");
  });

  it("la barre laterale est HORS de la zone qui defile", () => {
    rendre();
    const main = screen.getByRole("main");
    const barre = document.querySelector("aside") as HTMLElement;
    expect(barre).toBeInTheDocument();
    expect(main.contains(barre)).toBe(false);
  });

  it("sur ordinateur, la barre laterale suit la hauteur du cadre (et non plus statique a hauteur libre)", () => {
    rendre();
    const barre = document.querySelector("aside") as HTMLElement;
    expect(barre).toHaveClass("md:h-full");
  });

  it("la navigation defile seule si l'ecran est trop court, le menu utilisateur reste ancre", () => {
    rendre();
    const nav = document.querySelector("aside nav") as HTMLElement;
    expect(nav).toHaveClass("overflow-y-auto");
    const menu = screen.getByRole("button", { name: /menu du profil/i });
    expect(menu.closest("aside")).not.toBeNull();
    // le bloc du menu utilisateur ne retrecit pas
    expect(menu.closest("div.shrink-0")).not.toBeNull();
  });

  it("le nom d'utilisateur est visible aussi sur mobile et complet en infobulle quand il est tronque", () => {
    rendre();
    const nom = screen.getAllByText(/Prenom Nom-De-Famille/)[0];
    expect(nom).toHaveClass("truncate");
    expect(nom).toHaveAttribute("title", expect.stringContaining("Nom-De-Famille-Tres-Long"));
    // Avant : `hidden ... sm:flex` masquait le nom dans le tiroir mobile.
    expect(nom.parentElement).not.toHaveClass("hidden");
  });

  it("revient en haut de la zone de contenu quand on change de page", () => {
    const { rerender } = rendre();
    scrollToMock.mockClear();

    pathname = "/notes-frais";
    rerender(
      <AppLayout>
        <p>Contenu</p>
      </AppLayout>
    );

    expect(scrollToMock).toHaveBeenCalledWith({ top: 0 });
  });
});

describe("TableScroll", () => {
  it("laisse un tableau large defiler dans son cadre au lieu d'etre coupe", () => {
    render(
      <TableScroll data-testid="zone">
        <table>
          <tbody>
            <tr>
              <td>cellule</td>
            </tr>
          </tbody>
        </table>
      </TableScroll>
    );
    const zone = screen.getByTestId("zone");
    expect(zone).toHaveClass("overflow-x-auto", "w-full");
    expect(zone.querySelector("table")).toBeInTheDocument();
  });
});
