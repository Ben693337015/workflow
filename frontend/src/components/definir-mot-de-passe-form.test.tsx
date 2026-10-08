import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: replaceMock }) }));

const ouvrirSessionMock = vi.fn();
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ ouvrirSession: ouvrirSessionMock }) }));

const definirMotDePasseMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, definirMotDePasse: (...a: unknown[]) => definirMotDePasseMock(...a) };
});

import { ApiError } from "@/lib/api";
import { DefinirMotDePasseForm } from "./definir-mot-de-passe-form";

async function remplir(motDePasse: string, confirmation: string) {
  const user = userEvent.setup();
  await user.type(document.getElementById("mot-de-passe") as HTMLInputElement, motDePasse);
  await user.type(document.getElementById("confirmation") as HTMLInputElement, confirmation);
  await user.click(screen.getByRole("button"));
}

beforeEach(() => {
  vi.clearAllMocks();
  definirMotDePasseMock.mockResolvedValue({ connecte: true });
  ouvrirSessionMock.mockResolvedValue(undefined);
});

describe("DefinirMotDePasseForm (R23 : session par cookies)", () => {
  it("définit le mot de passe, charge la session (cookies posés par le proxy) puis redirige", async () => {
    render(<DefinirMotDePasseForm mode="invitation" jeton="jeton-lien" />);

    await remplir("MotDePasse123!", "MotDePasse123!");

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/mes-demandes"));
    expect(definirMotDePasseMock).toHaveBeenCalledWith("jeton-lien", "MotDePasse123!");
    expect(ouvrirSessionMock).toHaveBeenCalledTimes(1);
  });

  it("refuse deux mots de passe différents sans appeler l'API", async () => {
    render(<DefinirMotDePasseForm mode="invitation" jeton="jeton-lien" />);

    await remplir("MotDePasse123!", "AutreMotDePasse!");

    expect(await screen.findByText(/ne correspondent pas/i)).toBeInTheDocument();
    expect(definirMotDePasseMock).not.toHaveBeenCalled();
  });

  it("refuse un mot de passe de moins de 8 caractères", async () => {
    render(<DefinirMotDePasseForm mode="reinitialisation" jeton="jeton-lien" />);

    await remplir("court", "court");

    expect(await screen.findByText(/au moins 8 caractères/i)).toBeInTheDocument();
    expect(definirMotDePasseMock).not.toHaveBeenCalled();
  });

  it("un lien invalide ou expiré affiche une erreur et n'ouvre aucune session", async () => {
    definirMotDePasseMock.mockRejectedValue(new ApiError(401, "Lien expiré"));
    render(<DefinirMotDePasseForm mode="invitation" jeton="jeton-lien" />);

    await remplir("MotDePasse123!", "MotDePasse123!");

    expect(await screen.findByText(/invalide, a expiré/i)).toBeInTheDocument();
    expect(ouvrirSessionMock).not.toHaveBeenCalled();
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
