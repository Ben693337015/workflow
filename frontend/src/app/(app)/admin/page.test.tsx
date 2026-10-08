import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const listerTousLesComptesMock = vi.fn();
const creerCompteMock = vi.fn();
const desactiverCompteMock = vi.fn();
const reactiverCompteMock = vi.fn();
const modifierCompteMock = vi.fn();
const listerTypesCongeMock = vi.fn();
const creerTypeCongeMock = vi.fn();
const desactiverTypeCongeMock = vi.fn();
const reactiverTypeCongeMock = vi.fn();
const listerSoldesCongesMock = vi.fn();
const definirSoldeCongesMock = vi.fn();
const listerEnveloppesMock = vi.fn();
const definirEnveloppeMock = vi.fn();
const listerTauxChangeMock = vi.fn();
const definirTauxChangeMock = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listerTousLesComptes: (...a: unknown[]) => listerTousLesComptesMock(...a),
    creerCompte: (...a: unknown[]) => creerCompteMock(...a),
    desactiverCompte: (...a: unknown[]) => desactiverCompteMock(...a),
    reactiverCompte: (...a: unknown[]) => reactiverCompteMock(...a),
    modifierCompte: (...a: unknown[]) => modifierCompteMock(...a),
    listerTypesConge: (...a: unknown[]) => listerTypesCongeMock(...a),
    creerTypeConge: (...a: unknown[]) => creerTypeCongeMock(...a),
    desactiverTypeConge: (...a: unknown[]) => desactiverTypeCongeMock(...a),
    reactiverTypeConge: (...a: unknown[]) => reactiverTypeCongeMock(...a),
    listerSoldesConges: (...a: unknown[]) => listerSoldesCongesMock(...a),
    definirSoldeConges: (...a: unknown[]) => definirSoldeCongesMock(...a),
    listerEnveloppesBudgetaires: (...a: unknown[]) => listerEnveloppesMock(...a),
    definirEnveloppeBudgetaire: (...a: unknown[]) => definirEnveloppeMock(...a),
    listerTauxChange: (...a: unknown[]) => listerTauxChangeMock(...a),
    definirTauxChange: (...a: unknown[]) => definirTauxChangeMock(...a),
  };
});

import AdminPage from "./page";

const compteActif = { id: "u1", nom_complet: "Aïcha Bello", email: "aicha@test.tld", role: "manager", service: "Ventes", actif: true };
const compteInactif = { id: "u2", nom_complet: "Paul Ndjock", email: "paul@test.tld", role: "employe", service: "Support", actif: false };
const typeActif = { id: "t1", code: "CP", nom: "Congé payé", actif: true };
const typeInactif = { id: "t2", code: "MAL", nom: "Congé maladie", actif: false };

beforeEach(() => {
  vi.clearAllMocks();
  listerEnveloppesMock.mockResolvedValue([]);
  listerTauxChangeMock.mockResolvedValue([]);
  listerTousLesComptesMock.mockResolvedValue([compteActif, compteInactif]);
  listerTypesCongeMock.mockResolvedValue([typeActif, typeInactif]);
  listerSoldesCongesMock.mockResolvedValue([
    { id: "s1", type_conge_id: "t1", exercice: 2026, jours_acquis: 25, jours_pris: 4, solde_jours: 21 },
  ]);
});

describe("AdminPage — onglet Comptes : manager", () => {
  const sansManager = { ...compteInactif, actif: true, manager_id: null };
  const chef = { ...compteActif, manager_id: null };
  const rattache = { id: "u3", nom_complet: "Eva Mbarga", email: "eva@test.tld", role: "employe", service: "Ventes", actif: true, manager_id: "u1" };

  it("signale un compte sans manager et en nomme un compte rattache", async () => {
    listerTousLesComptesMock.mockResolvedValue([chef, sansManager, rattache]);
    render(<AdminPage />);
    await screen.findByText("Eva Mbarga");
    const ligneEva = screen.getByText("Eva Mbarga").closest("tr")!;
    expect(within(ligneEva).getByText("Aïcha Bello")).toBeInTheDocument();
    const lignePaul = screen.getByText("Paul Ndjock").closest("tr")!;
    expect(within(lignePaul).getByText("Aucun manager")).toBeInTheDocument();
    expect(within(lignePaul).getByRole("button", { name: /attribuer le manager de paul/i })).toBeInTheDocument();
    expect(within(ligneEva).getByRole("button", { name: /changer le manager de eva/i })).toBeInTheDocument();
  });

  it("attribue un manager : n'offre que des comptes actifs non-employes et envoie manager_id", async () => {
    listerTousLesComptesMock.mockResolvedValue([chef, sansManager]);
    modifierCompteMock.mockResolvedValue({ ...sansManager, manager_id: "u1", demandes_reaffectees: 0 });
    render(<AdminPage />);
    await screen.findByText("Paul Ndjock");

    await userEvent.click(screen.getByRole("button", { name: /attribuer le manager de paul/i }));
    const choix = screen.getByLabelText("Manager de Paul Ndjock");
    const options = within(choix).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Aucun manager", "Aïcha Bello — Ventes"]);

    await userEvent.selectOptions(choix, "u1");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer/i }));

    await waitFor(() => expect(modifierCompteMock).toHaveBeenCalledWith("u2", { manager_id: "u1" }));
    expect(await screen.findByText(/Manager de Paul Ndjock : Aïcha Bello\./)).toBeInTheDocument();
  });

  it("annonce les demandes en cours transmises au nouveau manager", async () => {
    listerTousLesComptesMock.mockResolvedValue([chef, rattache]);
    modifierCompteMock.mockResolvedValue({ ...rattache, manager_id: null, demandes_reaffectees: 2 });
    render(<AdminPage />);
    await screen.findByText("Eva Mbarga");
    await userEvent.click(screen.getByRole("button", { name: /changer le manager de eva/i }));
    await userEvent.selectOptions(screen.getByLabelText("Manager de Eva Mbarga"), "");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    expect(await screen.findByText(/2 demandes en cours transmises au nouveau manager/)).toBeInTheDocument();
  });

  it("affiche le refus du serveur (ex. boucle hierarchique) sans fermer l'edition", async () => {
    const { ApiError } = await import("@/lib/api");
    listerTousLesComptesMock.mockResolvedValue([chef, rattache]);
    modifierCompteMock.mockRejectedValue(new ApiError(422, "Ce rattachement créerait une boucle."));
    render(<AdminPage />);
    await screen.findByText("Eva Mbarga");
    await userEvent.click(screen.getByRole("button", { name: /changer le manager de eva/i }));
    await userEvent.selectOptions(screen.getByLabelText("Manager de Eva Mbarga"), "");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    expect(await screen.findByText(/créerait une boucle/)).toBeInTheDocument();
    expect(screen.getByLabelText("Manager de Eva Mbarga")).toBeInTheDocument();
  });

  it("la creation de compte transmet le manager choisi", async () => {
    listerTousLesComptesMock.mockResolvedValue([chef]);
    creerCompteMock.mockResolvedValue({ ...compteActif, id: "u9" });
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");
    await userEvent.click(screen.getByRole("button", { name: /nouveau compte/i }));
    await userEvent.type(screen.getByLabelText("Nom complet"), "Nouveau");
    await userEvent.type(screen.getByLabelText("E-mail"), "n@test.tld");
    await userEvent.type(screen.getByLabelText("Service"), "IT");
    await userEvent.selectOptions(screen.getByLabelText("Manager (facultatif)"), "u1");
    await userEvent.click(screen.getByRole("button", { name: /créer le compte/i }));
    await waitFor(() =>
      expect(creerCompteMock).toHaveBeenCalledWith(expect.objectContaining({ manager_id: "u1" }))
    );
  });
});

describe("AdminPage — onglet Comptes", () => {
  it("charge et affiche la liste reelle des comptes", async () => {
    render(<AdminPage />);
    expect(await screen.findByText("Aïcha Bello")).toBeInTheDocument();
    expect(screen.getByText("Paul Ndjock")).toBeInTheDocument();
    expect(listerTousLesComptesMock).toHaveBeenCalledTimes(1);
  });

  it("cree un compte : le formulaire soumet le bon payload puis recharge la liste", async () => {
    creerCompteMock.mockResolvedValue({ ...compteActif, id: "u3" });
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");

    await userEvent.click(screen.getByRole("button", { name: /nouveau compte/i }));
    await userEvent.type(screen.getByLabelText("Nom complet"), "Nouvel Employé");
    await userEvent.type(screen.getByLabelText("E-mail"), "nouvel@test.tld");
    await userEvent.type(screen.getByLabelText("Service"), "IT");
    await userEvent.selectOptions(screen.getByLabelText("Rôle"), "manager");
    await userEvent.click(screen.getByRole("button", { name: /créer le compte/i }));

    await waitFor(() => {
      expect(creerCompteMock).toHaveBeenCalledWith({
        email: "nouvel@test.tld",
        nom_complet: "Nouvel Employé",
        service: "IT",
        role: "manager",
      });
    });
    // Rechargement : un appel initial + un apres creation
    await waitFor(() => expect(listerTousLesComptesMock).toHaveBeenCalledTimes(2));
  });

  it("desactiver un compte actif appelle desactiverCompte, pas reactiverCompte", async () => {
    desactiverCompteMock.mockResolvedValue({ ...compteActif, actif: false });
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");

    const ligneAicha = screen.getByText("Aïcha Bello").closest("tr")!;
    await userEvent.click(within(ligneAicha).getByRole("button", { name: /désactiver/i }));

    await waitFor(() => expect(desactiverCompteMock).toHaveBeenCalledWith("u1"));
    expect(reactiverCompteMock).not.toHaveBeenCalled();
  });

  it("reactiver un compte desactive appelle reactiverCompte, pas desactiverCompte", async () => {
    reactiverCompteMock.mockResolvedValue({ ...compteInactif, actif: true });
    render(<AdminPage />);
    await screen.findByText("Paul Ndjock");

    const lignePaul = screen.getByText("Paul Ndjock").closest("tr")!;
    await userEvent.click(within(lignePaul).getByRole("button", { name: /réactiver/i }));

    await waitFor(() => expect(reactiverCompteMock).toHaveBeenCalledWith("u2"));
    expect(desactiverCompteMock).not.toHaveBeenCalled();
  });

  it("erreur de creation affichee, sans faire disparaitre le formulaire ni planter la page", async () => {
    creerCompteMock.mockRejectedValue(new Error("boom"));
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");

    await userEvent.click(screen.getByRole("button", { name: /nouveau compte/i }));
    await userEvent.type(screen.getByLabelText("Nom complet"), "X");
    await userEvent.type(screen.getByLabelText("E-mail"), "x@test.tld");
    await userEvent.type(screen.getByLabelText("Service"), "IT");
    await userEvent.click(screen.getByRole("button", { name: /créer le compte/i }));

    expect(await screen.findByText(/impossible de créer le compte/i)).toBeInTheDocument();
  });
});

describe("AdminPage — onglet Types de congé", () => {
  async function allerSurOngletTypes() {
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");
    await userEvent.click(screen.getByRole("button", { name: /^types de congé$/i }));
    await screen.findByText("Congé payé");
  }

  it("charge les types en incluant les inactifs (parametre true)", async () => {
    await allerSurOngletTypes();
    expect(listerTypesCongeMock).toHaveBeenCalledWith(true);
    expect(screen.getByText("Congé maladie")).toBeInTheDocument();
  });

  it("cree un type de conge avec le taux converti en nombre", async () => {
    creerTypeCongeMock.mockResolvedValue(typeActif);
    await allerSurOngletTypes();

    await userEvent.click(screen.getByRole("button", { name: /nouveau type/i }));
    await userEvent.type(screen.getByLabelText("Code"), "CSS");
    await userEvent.type(screen.getByLabelText("Nom"), "Congé sans solde");
    const champTaux = screen.getByLabelText("Jours/mois");
    await userEvent.clear(champTaux);
    await userEvent.type(champTaux, "1.5");
    await userEvent.click(screen.getByRole("button", { name: /créer le type/i }));

    await waitFor(() => {
      expect(creerTypeCongeMock).toHaveBeenCalledWith({
        code: "CSS",
        nom: "Congé sans solde",
        taux_acquisition_jours_mois: 1.5,
      });
    });
  });

  it("desactiver/reactiver un type appelle la bonne fonction selon son etat actuel", async () => {
    desactiverTypeCongeMock.mockResolvedValue({ ...typeActif, actif: false });
    reactiverTypeCongeMock.mockResolvedValue({ ...typeInactif, actif: true });
    await allerSurOngletTypes();

    const ligneActive = screen.getByText("Congé payé").closest("tr")!;
    await userEvent.click(within(ligneActive).getByRole("button", { name: /désactiver/i }));
    await waitFor(() => expect(desactiverTypeCongeMock).toHaveBeenCalledWith("t1"));

    const ligneInactive = screen.getByText("Congé maladie").closest("tr")!;
    await userEvent.click(within(ligneInactive).getByRole("button", { name: /réactiver/i }));
    await waitFor(() => expect(reactiverTypeCongeMock).toHaveBeenCalledWith("t2"));
  });
});

describe("AdminPage — onglet Soldes", () => {
  async function allerSurOngletSoldes() {
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");
    await userEvent.click(screen.getByRole("button", { name: /soldes de congés/i }));
    await screen.findByLabelText("Employé");
  }

  it("charge les soldes du premier employe au montage", async () => {
    await allerSurOngletSoldes();
    await waitFor(() => expect(listerSoldesCongesMock).toHaveBeenCalledWith("u1"));
    expect(await screen.findByText(21)).toBeInTheDocument();
  });

  it("changer l'employe selectionne recharge ses soldes", async () => {
    await allerSurOngletSoldes();
    listerSoldesCongesMock.mockClear();
    listerSoldesCongesMock.mockResolvedValue([
      { id: "s2", type_conge_id: "t1", exercice: 2026, jours_acquis: 25, jours_pris: 0, solde_jours: 25 },
    ]);

    await userEvent.selectOptions(screen.getByLabelText("Employé"), "u2");

    await waitFor(() => expect(listerSoldesCongesMock).toHaveBeenCalledWith("u2"));
  });

  it("enregistrer un solde appelle definirSoldeConges avec l'exercice courant", async () => {
    definirSoldeCongesMock.mockResolvedValue({
      id: "s1",
      type_conge_id: "t1",
      exercice: new Date().getFullYear(),
      jours_acquis: 30,
      jours_pris: 4,
      solde_jours: 26,
    });
    await allerSurOngletSoldes();

    const champJours = screen.getByLabelText("Jours acquis");
    await userEvent.clear(champJours);
    await userEvent.type(champJours, "30");
    await userEvent.click(screen.getByRole("button", { name: /^enregistrer$/i }));

    await waitFor(() => {
      expect(definirSoldeCongesMock).toHaveBeenCalledWith("u1", {
        type_conge_id: "t1",
        exercice: new Date().getFullYear(),
        jours_acquis: 30,
      });
    });
  });

  it("erreur d'enregistrement affichee sans planter la page", async () => {
    definirSoldeCongesMock.mockRejectedValue(new Error("boom"));
    await allerSurOngletSoldes();

    await userEvent.click(screen.getByRole("button", { name: /^enregistrer$/i }));

    expect(await screen.findByText(/impossible d'enregistrer ce solde/i)).toBeInTheDocument();
  });
});


describe("AdminPage — onglet Budgets", () => {
  async function allerSurOngletBudgets() {
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");
    await userEvent.click(screen.getByRole("button", { name: /^budgets$/i }));
    await screen.findByText(/enveloppes budgétaires/i);
  }

  it("liste les enveloppes avec le solde, en rouge si dépassement accepté", async () => {
    listerEnveloppesMock.mockResolvedValue([
      { id: "b1", service: "Ventes", exercice: 2026, budget_alloue: 1000, budget_consomme: 1300, solde_disponible: -300 },
    ]);
    await allerSurOngletBudgets();

    expect(await screen.findByText("Ventes")).toBeInTheDocument();
    expect(screen.getByText(/^-300,00\s€$/)).toHaveClass("text-danger");
  });

  it("enregistre une enveloppe avec le bon payload puis recharge", async () => {
    definirEnveloppeMock.mockResolvedValue({});
    await allerSurOngletBudgets();

    await userEvent.type(screen.getByLabelText("Service"), "Ventes");
    const exercice = screen.getByLabelText("Exercice");
    await userEvent.clear(exercice);
    await userEvent.type(exercice, "2026");
    await userEvent.type(screen.getByLabelText(/budget alloué/i), "5000");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer l'enveloppe/i }));

    await waitFor(() =>
      expect(definirEnveloppeMock).toHaveBeenCalledWith({ service: "Ventes", exercice: 2026, budget_alloue: 5000 })
    );
    await waitFor(() => expect(listerEnveloppesMock).toHaveBeenCalledTimes(2));
  });

  it("propose les services réellement présents dans les comptes", async () => {
    const { container } = render(<AdminPage />);
    await screen.findByText("Aïcha Bello");
    await userEvent.click(screen.getByRole("button", { name: /^budgets$/i }));
    await screen.findByText(/enveloppes budgétaires/i);

    await waitFor(() => {
      const valeurs = Array.from(container.querySelectorAll("datalist option")).map((o) => o.getAttribute("value"));
      expect(valeurs).toEqual(["Support", "Ventes"]);
    });
  });
});


describe("AdminPage — onglet Devises", () => {
  async function allerSurOngletDevises() {
    render(<AdminPage />);
    await screen.findByText("Aïcha Bello");
    await userEvent.click(screen.getByRole("button", { name: /^devises$/i }));
    await screen.findByText(/taux de change/i);
  }

  it("liste les taux existants", async () => {
    listerTauxChangeMock.mockResolvedValue([{ id: "t1", devise: "USD", taux: 0.92, date_effet: "2026-01-01" }]);
    await allerSurOngletDevises();

    expect(await screen.findByText("USD")).toBeInTheDocument();
    expect(screen.getByText("0.92")).toBeInTheDocument();
    expect(screen.getByText("01/01/2026")).toBeInTheDocument();
  });

  it("aucun taux : message explicite (seul l'euro reste utilisable)", async () => {
    await allerSurOngletDevises();
    expect(await screen.findByText(/seul l'euro est utilisable/i)).toBeInTheDocument();
  });

  it("enregistre un taux : la devise saisie est envoyée en MAJUSCULES, puis la liste est rechargée", async () => {
    definirTauxChangeMock.mockResolvedValue({});
    await allerSurOngletDevises();

    await userEvent.type(screen.getByLabelText(/devise \(code iso\)/i), "usd");
    await userEvent.type(screen.getByLabelText(/1 devise = x €/i), "0.92");
    const date = screen.getByLabelText(/date d'effet/i);
    await userEvent.clear(date);
    await userEvent.type(date, "2026-01-01");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer/i }));

    await waitFor(() => expect(definirTauxChangeMock).toHaveBeenCalledWith({ devise: "USD", taux: 0.92, date_effet: "2026-01-01" }));
    await waitFor(() => expect(listerTauxChangeMock).toHaveBeenCalledTimes(2));
  });

  it("échec d'enregistrement : erreur affichée", async () => {
    const { ApiError } = await import("@/lib/api");
    definirTauxChangeMock.mockRejectedValue(new ApiError(422, "Le taux doit être strictement positif."));
    await allerSurOngletDevises();

    await userEvent.type(screen.getByLabelText(/devise \(code iso\)/i), "usd");
    await userEvent.type(screen.getByLabelText(/1 devise = x €/i), "0");
    await userEvent.click(screen.getByRole("button", { name: /enregistrer/i }));

    expect(await screen.findByText(/le taux doit être strictement positif/i)).toBeInTheDocument();
  });
});
