import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

const quiSuisJeMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, quiSuisJe: (...a: unknown[]) => quiSuisJeMock(...a) };
});

import { AuthProvider, useAuth } from "./useAuth";
import { EVENEMENT_SESSION_EXPIREE } from "@/lib/api";

function Sonde() {
  const { connecte, chargement, utilisateur } = useAuth();
  if (chargement) return <p>chargement</p>;
  return <p>{connecte ? `connecte:${utilisateur?.nom_complet}` : "deconnecte"}</p>;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("workflows.session", "1"); // indicateur non sensible : les jetons sont en cookies httpOnly
  quiSuisJeMock.mockResolvedValue({ id: "1", nom_complet: "Aïcha Bello", email: "a@t.tld", role: "manager" });
});

describe("AuthProvider — expiration de session", () => {
  it("passe à déconnecté quand la session ne peut plus être renouvelée (renvoi vers /login par AppLayout)", async () => {
    render(
      <AuthProvider>
        <Sonde />
      </AuthProvider>
    );
    expect(await screen.findByText("connecte:Aïcha Bello")).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new Event(EVENEMENT_SESSION_EXPIREE));
    });

    await waitFor(() => expect(screen.getByText("deconnecte")).toBeInTheDocument());
  });
});
