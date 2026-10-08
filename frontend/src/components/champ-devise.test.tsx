import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, renderHook } from "@testing-library/react";
import "@testing-library/jest-dom";

const listerDevisesMock = vi.fn();
const convertirMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, listerDevises: (...a: unknown[]) => listerDevisesMock(...a), convertirMontant: (...a: unknown[]) => convertirMock(...a) };
});

import { ApercuConversion, ChampDevise, useDevises } from "./champ-devise";

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

describe("useDevises", () => {
  it("expose la référence et les devises utilisables", async () => {
    listerDevisesMock.mockResolvedValue({ reference: "EUR", devises: [{ code: "EUR", taux: 1, date_effet: null }, { code: "USD", taux: 0.92, date_effet: "2026-01-01" }] });
    const { result } = renderHook(() => useDevises());

    await vi.waitFor(() => expect(result.current.devises).toHaveLength(2));
    expect(result.current.reference).toBe("EUR");
  });

  it("reste sur EUR sans blocage si l'appel échoue", async () => {
    listerDevisesMock.mockRejectedValue(new Error("réseau"));
    const { result } = renderHook(() => useDevises());
    await vi.waitFor(() => expect(listerDevisesMock).toHaveBeenCalled());
    expect(result.current.reference).toBe("EUR");
    expect(result.current.devises).toEqual([]);
  });
});

describe("ChampDevise", () => {
  it("masqué tant qu'une seule devise existe", () => {
    const { container } = render(<ChampDevise id="d" valeur="EUR" onChange={() => {}} devises={[{ code: "EUR", taux: 1, date_effet: null }]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("affiché dès que plusieurs devises existent, avec la valeur sélectionnée", () => {
    render(<ChampDevise id="d" valeur="USD" onChange={() => {}} devises={[{ code: "EUR", taux: 1, date_effet: null }, { code: "USD", taux: 0.92, date_effet: null }]} />);
    expect(screen.getByLabelText("Devise")).toHaveValue("USD");
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });
});

describe("ApercuConversion", () => {
  it("rien pour la devise de référence, même avec un montant", async () => {
    const { container } = render(<ApercuConversion montant="100" devise="EUR" reference="EUR" />);
    vi.advanceTimersByTime(500);
    expect(container).toBeEmptyDOMElement();
    expect(convertirMock).not.toHaveBeenCalled();
  });

  it("anti-rebond : une frappe corrigée dans la fenêtre n'appelle l'API qu'une fois, avec la dernière valeur", async () => {
    convertirMock.mockResolvedValue({ devise: "USD", devise_reference: "EUR", taux: 0.92, montant: 80, montant_reference: 73.6, date_effet: "2026-01-01" });
    const { rerender } = render(<ApercuConversion montant="8" devise="USD" reference="EUR" />);
    vi.advanceTimersByTime(200);
    rerender(<ApercuConversion montant="80" devise="USD" reference="EUR" />);
    vi.advanceTimersByTime(500);

    await vi.waitFor(() => expect(convertirMock).toHaveBeenCalledTimes(1));
    expect(convertirMock).toHaveBeenCalledWith({ montant: 80, devise: "USD", date: undefined });
    expect(await screen.findByText(/≈ 73,60 €/)).toBeInTheDocument();
    expect(screen.getByText(/figé à l'envoi/)).toBeInTheDocument();
  });

  it("montant vide ou non numérique : aucun appel", () => {
    render(<ApercuConversion montant="" devise="USD" reference="EUR" />);
    vi.advanceTimersByTime(500);
    expect(convertirMock).not.toHaveBeenCalled();
  });

  it("erreur du backend affichée (ex. taux introuvable)", async () => {
    const { ApiError } = await import("@/lib/api");
    convertirMock.mockRejectedValue(new ApiError(422, "Aucun taux de change disponible pour GBP."));
    render(<ApercuConversion montant="10" devise="GBP" reference="EUR" />);
    vi.advanceTimersByTime(500);

    expect(await screen.findByText(/aucun taux de change disponible pour gbp/i)).toBeInTheDocument();
  });

  it("un composant démonté pendant l'attente n'écrit pas dans le vide (pas d'avertissement React)", async () => {
    convertirMock.mockResolvedValue({ devise: "USD", devise_reference: "EUR", taux: 0.9, montant: 10, montant_reference: 9, date_effet: null });
    const { unmount } = render(<ApercuConversion montant="10" devise="USD" reference="EUR" />);
    vi.advanceTimersByTime(500);
    unmount();
    await vi.waitFor(() => expect(convertirMock).toHaveBeenCalled());
  });
});
