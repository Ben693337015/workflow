import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const listerMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, listerMessages: (...a: unknown[]) => listerMock(...a) };
});
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ utilisateur: { id: "u-emp" } }) }));

import { DiscussionDialog } from "./discussion-dialog";

beforeEach(() => {
  vi.clearAllMocks();
  listerMock.mockResolvedValue([]);
});

describe("DiscussionDialog", () => {
  it("fermée (demandeId null) : rien n'est affiché et aucune discussion n'est chargée", () => {
    render(<DiscussionDialog demandeId={null} titre="Congé" onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(listerMock).not.toHaveBeenCalled();
  });

  it("ouverte : une vraie boîte de dialogue avec le rappel de la demande concernée", async () => {
    render(<DiscussionDialog demandeId="d1" titre="Congé du 2027-06-07 au 2027-06-08" onClose={() => {}} />);
    const boite = await screen.findByRole("dialog");
    expect(boite).toHaveTextContent("Précisions demandées");
    expect(boite).toHaveTextContent("Congé du 2027-06-07 au 2027-06-08");
    await waitFor(() => expect(listerMock).toHaveBeenCalledWith("d1"));
  });

  it("le bouton Fermer et la touche Échap appellent onClose", async () => {
    const onClose = vi.fn();
    render(<DiscussionDialog demandeId="d1" titre="Congé" onClose={onClose} />);
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Fermer" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
