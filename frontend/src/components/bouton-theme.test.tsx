import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BoutonTheme, CLE_THEME, SCRIPT_THEME } from "./bouton-theme";

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

describe("BoutonTheme", () => {
  it("bascule vers le mode sombre, memorise le choix et change son libelle", () => {
    document.documentElement.setAttribute("data-theme", "light");
    render(<BoutonTheme />);
    fireEvent.click(screen.getByRole("button", { name: "Passer en mode sombre" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(CLE_THEME)).toBe("dark");
    expect(screen.getByRole("button", { name: "Passer en mode clair" })).toBeTruthy();
  });

  it("rebascule vers le mode clair", () => {
    document.documentElement.setAttribute("data-theme", "dark");
    render(<BoutonTheme />);
    fireEvent.click(screen.getByRole("button", { name: "Passer en mode clair" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(CLE_THEME)).toBe("light");
  });

  it("le script de demarrage applique le choix memorise, ignore une valeur inconnue", () => {
    localStorage.setItem(CLE_THEME, "dark");
    new Function(SCRIPT_THEME)();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem(CLE_THEME, "n'importe quoi");
    new Function(SCRIPT_THEME)();
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
  });
});
