import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const listerMock = vi.fn();
const envoyerMock = vi.fn();
const reprendreMock = vi.fn();
const avecFichierMock = vi.fn();
const telechargerMock = vi.fn();
const enregistrerMock = vi.fn();
vi.mock("@/lib/telechargement", () => ({ enregistrerFichier: (...a: unknown[]) => enregistrerMock(...a) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listerMessages: (...a: unknown[]) => listerMock(...a),
    envoyerMessage: (...a: unknown[]) => envoyerMock(...a),
    reprendreDemande: (...a: unknown[]) => reprendreMock(...a),
    envoyerMessageAvecFichier: (...a: unknown[]) => avecFichierMock(...a),
    telechargerFichierMessage: (...a: unknown[]) => telechargerMock(...a),
  };
});

import { DiscussionPanel, INTERVALLE_RAFRAICHISSEMENT_MS } from "./discussion-panel";

const messages = [
  { id: "m1", auteur_id: "u1", auteur_nom: "Manager Test", contenu: "Justificatif illisible.", cree_le: "2026-06-01T10:00:00Z" },
];

beforeEach(() => {
  vi.clearAllMocks();
  listerMock.mockResolvedValue(messages);
});

describe("DiscussionPanel", () => {
  it("affiche les messages avec leur auteur", async () => {
    render(<DiscussionPanel demandeId="d1" />);

    expect(await screen.findByText("Justificatif illisible.")).toBeInTheDocument();
    expect(screen.getByText("Manager Test")).toBeInTheDocument();
    expect(listerMock).toHaveBeenCalledWith("d1");
  });

  it("envoie un message, vide le champ et recharge la discussion", async () => {
    envoyerMock.mockResolvedValue({});
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");

    await userEvent.type(screen.getByLabelText("Votre message"), "Voici une meilleure version.");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));

    await waitFor(() => expect(envoyerMock).toHaveBeenCalledWith("d1", "Voici une meilleure version."));
    await waitFor(() => expect(screen.getByLabelText("Votre message")).toHaveValue(""));
    expect(listerMock).toHaveBeenCalledTimes(2);
  });

  it("le bouton Envoyer reste désactivé tant que le message est vide", async () => {
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    expect(screen.getByRole("button", { name: "Envoyer" })).toBeDisabled();
  });

  it("le bouton de reprise n'existe que côté approbateur (onReprise fourni)", async () => {
    const { rerender } = render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    expect(screen.queryByRole("button", { name: /reprendre le workflow/i })).not.toBeInTheDocument();

    const onReprise = vi.fn();
    reprendreMock.mockResolvedValue({ id: "d1", statut_global: "en_cours" });
    rerender(<DiscussionPanel demandeId="d1" onReprise={onReprise} />);
    await userEvent.click(screen.getByRole("button", { name: /reprendre le workflow/i }));

    await waitFor(() => expect(reprendreMock).toHaveBeenCalledWith("d1"));
    expect(onReprise).toHaveBeenCalled();
  });

  it("affiche l'erreur du backend (ex. 403 hors échange)", async () => {
    const { ApiError } = await import("@/lib/api");
    listerMock.mockRejectedValue(new ApiError(403, "Accès refusé à cette discussion."));
    render(<DiscussionPanel demandeId="d1" />);

    expect(await screen.findByText(/accès refusé à cette discussion/i)).toBeInTheDocument();
  });

  it("avec une pièce sélectionnée, envoie via l'envoi multipart (pas l'envoi JSON) puis vide le champ", async () => {
    avecFichierMock.mockResolvedValue({});
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");

    const piece = new File(["%PDF"], "justificatif.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/pièce complémentaire/i), piece);
    await userEvent.type(screen.getByLabelText("Votre message"), "Voici la pièce.");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));

    await waitFor(() => expect(avecFichierMock).toHaveBeenCalledWith("d1", "Voici la pièce.", piece));
    expect(envoyerMock).not.toHaveBeenCalled();
    await waitFor(() => expect((screen.getByLabelText(/pièce complémentaire/i) as HTMLInputElement).files).toHaveLength(0));
  });

  it("un message portant une pièce affiche un bouton qui la télécharge sous son nom", async () => {
    listerMock.mockResolvedValue([{ ...messages[0], id: "m9", fichier_nom: "facture.pdf" }]);
    telechargerMock.mockResolvedValue(new Blob(["contenu"]));
    render(<DiscussionPanel demandeId="d1" />);

    await userEvent.click(await screen.findByRole("button", { name: /facture\.pdf/ }));

    await waitFor(() => expect(telechargerMock).toHaveBeenCalledWith("d1", "m9"));
    expect(enregistrerMock).toHaveBeenCalledWith(expect.any(Blob), "facture.pdf");
  });

  it("un message sans pièce n'affiche aucun bouton de téléchargement", async () => {
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    expect(screen.queryByRole("button", { name: /\.pdf/ })).not.toBeInTheDocument();
  });
});

describe("DiscussionPanel — rafraîchissement automatique (échange réellement bidirectionnel)", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("recharge la discussion à intervalle régulier : une réponse de l'autre partie apparaît sans rechargement de page", async () => {
    listerMock.mockResolvedValueOnce(messages).mockResolvedValue([
      ...messages,
      { id: "m2", auteur_id: "u2", auteur_nom: "Aïcha Bello", contenu: "Voici la version lisible.", cree_le: "2026-06-01T11:00:00Z" },
    ]);
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    expect(screen.queryByText("Voici la version lisible.")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTERVALLE_RAFRAICHISSEMENT_MS + 50);
    });

    expect(await screen.findByText("Voici la version lisible.")).toBeInTheDocument();
  });

  it("arrête le rafraîchissement quand le composant est démonté", async () => {
    const { unmount } = render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    const appels = listerMock.mock.calls.length;

    unmount();
    await vi.advanceTimersByTimeAsync(INTERVALLE_RAFRAICHISSEMENT_MS * 3);

    expect(listerMock).toHaveBeenCalledTimes(appels);
  });
});

describe("DiscussionPanel — lisibilité de l'échange", () => {
  it("affiche « Aucun message pour le moment » une fois chargé sans message (pas pendant le chargement)", async () => {
    listerMock.mockResolvedValue([]);
    render(<DiscussionPanel demandeId="d1" />);
    expect(await screen.findByText("Aucun message pour le moment.")).toBeInTheDocument();
  });

  it("repère par « (vous) » les messages de l'utilisateur connecté, pas ceux de l'autre partie", async () => {
    listerMock.mockResolvedValue([
      { id: "m1", auteur_id: "u-mgr", auteur_nom: "Manager Test", contenu: "Précisez.", cree_le: "2026-10-01T10:00:00Z" },
      { id: "m2", auteur_id: "u-emp", auteur_nom: "Employé Test", contenu: "Voici.", cree_le: "2026-10-01T11:00:00Z" },
    ]);
    render(<DiscussionPanel demandeId="d1" utilisateurId="u-emp" />);
    expect(await screen.findByText(/Employé Test \(vous\)/)).toBeInTheDocument();
    expect(screen.getByText("Manager Test")).toBeInTheDocument();
    expect(screen.queryByText(/Manager Test \(vous\)/)).not.toBeInTheDocument();
  });

  it("horodate chaque message (balise <time> avec la date d'origine)", async () => {
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    const heure = document.querySelector("time");
    expect(heure).toHaveAttribute("datetime", "2026-06-01T10:00:00Z");
    expect(heure?.textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });
});

describe("DiscussionPanel — taille des pièces (40 Mo)", () => {
  function gros(octets: number): File {
    const f = new File(["x"], "enorme.pdf", { type: "application/pdf" });
    Object.defineProperty(f, "size", { value: octets });
    return f;
  }

  it("refuse avant tout envoi une pièce de plus de 40 Mo et n'appelle pas le serveur", async () => {
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    await userEvent.type(screen.getByLabelText("Votre message"), "Voici");
    await userEvent.upload(screen.getByLabelText(/Pièce complémentaire/), gros(40 * 1024 * 1024 + 1));
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));

    expect(await screen.findByText("Le fichier dépasse la taille maximale autorisée (40 Mo).")).toBeInTheDocument();
    expect(avecFichierMock).not.toHaveBeenCalled();
    expect(envoyerMock).not.toHaveBeenCalled();
  });

  it("envoie une pièce de 35 Mo (refusée avant le passage à 40 Mo)", async () => {
    avecFichierMock.mockResolvedValue({});
    render(<DiscussionPanel demandeId="d1" />);
    await screen.findByText("Justificatif illisible.");
    await userEvent.type(screen.getByLabelText("Votre message"), "Voici");
    await userEvent.upload(screen.getByLabelText(/Pièce complémentaire/), gros(35 * 1024 * 1024));
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));

    await waitFor(() => expect(avecFichierMock).toHaveBeenCalledTimes(1));
  });
});
