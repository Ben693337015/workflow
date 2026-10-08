import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const listerMock = vi.fn(); // congés
const listerNotesMock = vi.fn();
const listerAchatsMock = vi.fn();
const annulerMock = vi.fn();
const relancerMock = vi.fn();
const annulerNoteMock = vi.fn();
const annulerAchatMock = vi.fn();
const telechargerFicheMock = vi.fn();
const contratMock = vi.fn();
const bcMock = vi.fn();
const listerMessagesMock = vi.fn();
const listerDevisesMock = vi.fn();
let parametresUrl = "";
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(parametresUrl) }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ utilisateur: { id: "u-moi" } }) }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listerMesDemandesConges: (...a: unknown[]) => listerMock(...a),
    listerMesNotesDeFrais: (...a: unknown[]) => listerNotesMock(...a),
    listerMesDemandesAchat: (...a: unknown[]) => listerAchatsMock(...a),
    annulerDemandeConges: (...a: unknown[]) => annulerMock(...a),
    relancerNotificationConges: (...a: unknown[]) => relancerMock(...a),
    annulerNoteDeFrais: (...a: unknown[]) => annulerNoteMock(...a),
    annulerDemandeAchat: (...a: unknown[]) => annulerAchatMock(...a),
    telechargerFicheConfirmation: (...a: unknown[]) => telechargerFicheMock(...a),
    telechargerContratAchat: (...a: unknown[]) => contratMock(...a),
    telechargerBonDeCommande: (...a: unknown[]) => bcMock(...a),
    listerMessages: (...a: unknown[]) => listerMessagesMock(...a),
    listerDevises: (...a: unknown[]) => listerDevisesMock(...a),
  };
});

import MesDemandesPage from "./page";

const demande = (id: string, statut: string, extra = {}) => ({
  id,
  statut_global: statut,
  donnees: { date_debut: "2026-06-01", date_fin: "2026-06-03", commentaire: "" },
  pieces_jointes: [],
  ...extra,
});
const note = (id: string, statut: string, categorie = "Repas", extra = {}) => ({
  id,
  statut_global: statut,
  donnees: { montant: 80, categorie, date_depense: "2026-02-10", description: "x" },
  pieces_jointes: [],
  ...extra,
});
const achat = (id: string, statut: string, tiers = "Fournisseur Y", extra = {}) => ({
  id,
  statut_global: statut,
  donnees: { tiers, objet: "x", budget_engage: 120 },
  ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  parametresUrl = "";
  listerMessagesMock.mockResolvedValue([]);
  listerMock.mockResolvedValue([]);
  listerNotesMock.mockResolvedValue([]);
  listerAchatsMock.mockResolvedValue([]);
  listerDevisesMock.mockResolvedValue({ reference: "EUR", devises: [{ code: "EUR", taux: 1, date_effet: null }] });
});

describe("MesDemandesPage — congés", () => {
  it("affiche chaque demande avec sa période et son statut", async () => {
    listerMock.mockResolvedValue([demande("d1", "en_cours")]);
    render(<MesDemandesPage />);

    expect(await screen.findByText("2026-06-01 — 2026-06-03")).toBeInTheDocument();
    expect(screen.getByText("En cours")).toBeInTheDocument();
  });

  it("aucune demande : message clair et un lien vers chacun des trois formulaires", async () => {
    listerMock.mockResolvedValue([]);
    render(<MesDemandesPage />);
    expect(await screen.findByText(/aucune demande pour l'instant/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /poser un congé/i })).toHaveAttribute("href", "/nouvelle-demande");
    expect(screen.getByRole("link", { name: /déclarer une note de frais/i })).toHaveAttribute("href", "/notes-frais");
    expect(screen.getByRole("link", { name: /demande d'achat/i })).toHaveAttribute("href", "/achats");
  });

  it("échec de chargement : erreur affichée", async () => {
    const { ApiError } = await import("@/lib/api");
    listerMock.mockRejectedValue(new ApiError(500, "Erreur serveur."));
    render(<MesDemandesPage />);
    expect(await screen.findByText("Erreur serveur.")).toBeInTheDocument();
  });

  it("une demande en cours propose Annuler et Relancer ; une demande terminée propose Fiche, pas Annuler", async () => {
    listerMock.mockResolvedValue([demande("d1", "en_cours"), demande("d2", "terminee", { donnees: { date_debut: "2026-07-01", date_fin: "2026-07-03", commentaire: "" } })]);
    render(<MesDemandesPage />);
    await screen.findByText("2026-06-01 — 2026-06-03");

    expect(screen.getByRole("button", { name: "Annuler" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Relancer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /fiche/i })).toBeInTheDocument();
  });

  it("annuler une demande recharge la liste", async () => {
    listerMock.mockResolvedValueOnce([demande("d1", "en_cours")]).mockResolvedValueOnce([demande("d1", "annulee")]);
    annulerMock.mockResolvedValue({ id: "d1", statut_global: "annulee" });
    render(<MesDemandesPage />);
    await screen.findByRole("button", { name: "Annuler" });

    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));

    await waitFor(() => expect(annulerMock).toHaveBeenCalledWith("d1"));
    expect(await screen.findByText("Annulée")).toBeInTheDocument();
  });

  it("relancer affiche le retour du backend sans recharger la liste (le statut ne change pas)", async () => {
    listerMock.mockResolvedValue([demande("d1", "en_cours")]);
    relancerMock.mockResolvedValue({ id: "d1", email_envoye: true, detail: "Notification renvoyée au manager." });
    render(<MesDemandesPage />);
    await screen.findByRole("button", { name: "Relancer" });

    await userEvent.click(screen.getByRole("button", { name: "Relancer" }));

    expect(await screen.findByText("Notification renvoyée au manager.")).toBeInTheDocument();
    expect(listerMock).toHaveBeenCalledTimes(1); // un seul chargement initial, aucun rechargement
  });

  it("une demande en attente de précisions propose Annuler et Discussion, mais pas Relancer", async () => {
    listerMock.mockResolvedValue([demande("d1", "complement_demande")]);
    render(<MesDemandesPage />);

    expect(await screen.findByRole("button", { name: "Annuler" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discussion" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Relancer" })).not.toBeInTheDocument();
  });

  it("cliquer sur Discussion ouvre une boîte de dialogue qui rappelle la demande concernée", async () => {
    listerMock.mockResolvedValue([demande("d1", "complement_demande")]);
    render(<MesDemandesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Discussion" }));

    const boite = await screen.findByRole("dialog");
    expect(boite).toHaveTextContent("Précisions demandées");
    expect(boite).toHaveTextContent("Congé du 2026-06-01 au 2026-06-03");
    expect(listerMessagesMock).toHaveBeenCalledWith("d1");
  });

  it("fermer la boîte de dialogue la retire de l'écran", async () => {
    listerMock.mockResolvedValue([demande("d1", "complement_demande")]);
    render(<MesDemandesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Discussion" }));
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("button", { name: "Fermer" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("télécharge la fiche de confirmation", async () => {
    listerMock.mockResolvedValue([demande("d1", "terminee")]);
    telechargerFicheMock.mockResolvedValue(new Blob(["%PDF"]));
    const creerUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    const revoquerUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clic = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<MesDemandesPage />);

    await userEvent.click(await screen.findByRole("button", { name: /fiche/i }));

    await waitFor(() => expect(telechargerFicheMock).toHaveBeenCalledWith("d1"));
    expect(creerUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect(clic).toHaveBeenCalledTimes(1);
    creerUrl.mockRestore();
    revoquerUrl.mockRestore();
    clic.mockRestore();
  });

  it("échec du téléchargement de la fiche : erreur affichée", async () => {
    const { ApiError } = await import("@/lib/api");
    listerMock.mockResolvedValue([demande("d1", "terminee")]);
    telechargerFicheMock.mockRejectedValue(new ApiError(404, "Fiche introuvable."));
    render(<MesDemandesPage />);

    await userEvent.click(await screen.findByRole("button", { name: /fiche/i }));

    expect(await screen.findByText("Fiche introuvable.")).toBeInTheDocument();
  });
});

describe("MesDemandesPage — les trois types regroupés", () => {
  const toutCharger = () => {
    listerMock.mockResolvedValue([demande("d1", "en_cours", { creee_le: "2026-03-01T10:00:00Z" })]);
    listerNotesMock.mockResolvedValue([note("n1", "terminee", "Repas", { creee_le: "2026-03-03T10:00:00Z" })]);
    listerAchatsMock.mockResolvedValue([achat("a1", "refusee", "Fournisseur Y", { creee_le: "2026-03-02T10:00:00Z" })]);
  };

  it("une seule liste : congé, note de frais et achat, chacun avec sa pastille de type et son statut", async () => {
    toutCharger();
    render(<MesDemandesPage />);
    await screen.findByText("Repas");

    const lignes = within(screen.getByRole("table")).getAllByRole("row").slice(1); // sans l'en-tête
    expect(lignes).toHaveLength(3);
    expect(lignes[0]).toHaveTextContent("Note de frais");
    expect(lignes[0]).toHaveTextContent("Approuvée");
    expect(lignes[1]).toHaveTextContent("Achat");
    expect(lignes[1]).toHaveTextContent("Refusée");
    expect(lignes[2]).toHaveTextContent("Congé");
    expect(lignes[2]).toHaveTextContent("En cours");
  });

  it("trie par date de création décroissante : la plus récente d'abord", async () => {
    toutCharger();
    render(<MesDemandesPage />);
    await screen.findByText("Repas");
    const textes = within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => r.textContent ?? "");
    expect(textes[0]).toContain("Repas"); // 03/03
    expect(textes[1]).toContain("Fournisseur Y"); // 02/03
    expect(textes[2]).toContain("2026-06-01"); // 01/03
  });

  it("les onglets affichent un compteur par type et filtrent la liste", async () => {
    toutCharger();
    render(<MesDemandesPage />);
    await screen.findByText("Repas");

    expect(screen.getByRole("tab", { name: /toutes\s*3/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /congés\s*1/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /notes de frais\s*1/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /achats\s*1/i }));

    expect(screen.getByText("Fournisseur Y")).toBeInTheDocument();
    expect(screen.queryByText("Repas")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-06-01 — 2026-06-03")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /achats\s*1/i })).toHaveAttribute("aria-selected", "true");

    await userEvent.click(screen.getByRole("tab", { name: /toutes/i }));
    expect(screen.getByText("Repas")).toBeInTheDocument();
  });

  it("un filtre sans résultat l'indique et renvoie vers le bon formulaire", async () => {
    listerMock.mockResolvedValue([demande("d1", "en_cours")]);
    render(<MesDemandesPage />);
    await screen.findByText("2026-06-01 — 2026-06-03");

    await userEvent.click(screen.getByRole("tab", { name: /achats\s*0/i }));

    expect(screen.getByText(/aucune demande de ce type/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /demande d'achat/i })).toHaveAttribute("href", "/achats");
  });

  it("?type=notes_frais ouvre directement l'onglet des notes de frais (retour depuis le formulaire)", async () => {
    parametresUrl = "type=notes_frais";
    toutCharger();
    render(<MesDemandesPage />);
    await screen.findByText("Repas");

    expect(screen.getByRole("tab", { name: /notes de frais/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Fournisseur Y")).not.toBeInTheDocument();
  });

  it("une valeur ?type= inconnue retombe sur « Toutes »", async () => {
    parametresUrl = "type=n-importe-quoi";
    toutCharger();
    render(<MesDemandesPage />);
    await screen.findByText("Repas");
    expect(screen.getByRole("tab", { name: /toutes/i })).toHaveAttribute("aria-selected", "true");
  });

  it("la panne d'une liste n'empêche pas d'afficher les deux autres", async () => {
    const { ApiError } = await import("@/lib/api");
    listerMock.mockResolvedValue([demande("d1", "en_cours")]);
    listerNotesMock.mockRejectedValue(new ApiError(500, "Notes indisponibles."));
    listerAchatsMock.mockResolvedValue([achat("a1", "en_cours")]);
    render(<MesDemandesPage />);

    expect(await screen.findByText("Notes indisponibles.")).toBeInTheDocument();
    expect(screen.getByText("2026-06-01 — 2026-06-03")).toBeInTheDocument();
    expect(screen.getByText("Fournisseur Y")).toBeInTheDocument();
  });
});

describe("MesDemandesPage — notes de frais", () => {
  it("montre catégorie, date, montant et statut", async () => {
    listerNotesMock.mockResolvedValue([note("n1", "terminee")]);
    render(<MesDemandesPage />);

    expect(await screen.findByText("Repas")).toBeInTheDocument();
    expect(screen.getByText(/80,00 €/)).toBeInTheDocument();
    expect(screen.getByText("Approuvée")).toBeInTheDocument();
  });

  it("montre les reçus et ne propose l'ajout que tant que la note est ouverte", async () => {
    listerNotesMock.mockResolvedValue([
      note("n1", "en_cours", "Repas", { pieces_jointes: [{ id: "p1", nom: "ticket.pdf", categorie: "recu" }] }),
      note("n2", "terminee", "Taxi", { pieces_jointes: [{ id: "p2", nom: "course.pdf", categorie: "recu" }] }),
    ]);
    render(<MesDemandesPage />);

    expect(await screen.findByRole("button", { name: /ticket\.pdf/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /course\.pdf/ })).toBeInTheDocument();
    expect(screen.getAllByLabelText(/ajouter une pièce/i)).toHaveLength(1);
  });

  it("Discussion n'apparaît que pour une note dont des précisions sont demandées, avec son titre", async () => {
    listerNotesMock.mockResolvedValue([note("n1", "en_cours", "Repas"), note("n2", "complement_demande", "Transport", { donnees: { montant: 20, categorie: "Transport", date_depense: "2026-02-11", description: "x" } })]);
    listerMessagesMock.mockResolvedValue([{ id: "m1", auteur_id: "u", auteur_nom: "Manager", contenu: "Quel trajet ?", cree_le: "2026-02-12T10:00:00Z" }]);
    render(<MesDemandesPage />);

    await screen.findByText("Transport");
    const boutons = screen.getAllByRole("button", { name: "Discussion" });
    expect(boutons).toHaveLength(1);
    await userEvent.click(boutons[0]);
    expect(await screen.findByRole("dialog")).toHaveTextContent("Note de frais « Transport » du 2026-02-11");
    expect(listerMessagesMock).toHaveBeenCalledWith("n2");
  });

  it("annuler une note de frais recharge la liste", async () => {
    listerNotesMock.mockResolvedValueOnce([note("n1", "en_cours")]).mockResolvedValueOnce([note("n1", "annulee")]);
    annulerNoteMock.mockResolvedValue({ id: "n1", statut_global: "annulee" });
    render(<MesDemandesPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Annuler" }));

    await waitFor(() => expect(annulerNoteMock).toHaveBeenCalledWith("n1"));
    expect(await screen.findByText("Annulée")).toBeInTheDocument();
  });
});

describe("MesDemandesPage — achats", () => {
  it("le statut d'un achat terminé se lit « Signée »", async () => {
    listerAchatsMock.mockResolvedValue([achat("a1", "terminee", "Signée SARL", { donnees: { tiers: "Signée SARL", objet: "x", budget_engage: 20, numero_bc: "BC-2026-0001" } })]);
    render(<MesDemandesPage />);
    expect(await screen.findByText("Signée")).toBeInTheDocument();
  });

  it("le bon de commande n'est proposé que pour une demande terminée avec un numéro", async () => {
    listerAchatsMock.mockResolvedValue([
      achat("a1", "en_cours", "En cours SA"),
      achat("a2", "terminee", "Signée SARL", { donnees: { tiers: "Signée SARL", objet: "x", budget_engage: 20, numero_bc: "BC-2026-0001" } }),
    ]);
    bcMock.mockResolvedValue(new Blob(["pdf"]));
    URL.createObjectURL = vi.fn(() => "blob:test");
    URL.revokeObjectURL = vi.fn();
    render(<MesDemandesPage />);

    await screen.findByText("Signée SARL");
    expect(screen.getAllByRole("button", { name: /^contrat$/i })).toHaveLength(2);
    const boutonsBC = screen.getAllByRole("button", { name: /bon de commande/i });
    expect(boutonsBC).toHaveLength(1);
    await userEvent.click(boutonsBC[0]);
    await waitFor(() => expect(bcMock).toHaveBeenCalledWith("a2"));
  });

  it("annuler une demande d'achat recharge la liste", async () => {
    listerAchatsMock.mockResolvedValueOnce([achat("a1", "en_cours")]).mockResolvedValueOnce([achat("a1", "annulee")]);
    annulerAchatMock.mockResolvedValue({ id: "a1", statut_global: "annulee" });
    render(<MesDemandesPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Annuler" }));

    await waitFor(() => expect(annulerAchatMock).toHaveBeenCalledWith("a1"));
    expect(await screen.findByText("Annulée")).toBeInTheDocument();
  });

  it("affiche le nombre de lignes d'une demande détaillée", async () => {
    listerAchatsMock.mockResolvedValue([
      achat("a1", "en_cours", "Fournisseur Y", { donnees: { tiers: "Fournisseur Y", objet: "x", budget_engage: 120, lignes: [{ description: "A", montant_ht: 100, taux_tva: 20 }] } }),
    ]);
    render(<MesDemandesPage />);
    expect(await screen.findByText("(1 ligne)")).toBeInTheDocument();
  });
});
