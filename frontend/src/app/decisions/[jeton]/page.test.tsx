import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useParams: () => ({ jeton: "jeton-test-123" }),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
});

// Etat mutable pour simuler la transition reelle "non connecte" -> "connecte".
let etatConnecte = true;
const seConnecterMock = vi.fn(async () => {
  etatConnecte = true;
});

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    connecte: etatConnecte,
    chargement: false,
    utilisateur: etatConnecte
      ? { id: "1", nom_complet: "Test Manager", email: "m@test.tld", role: "manager" }
      : null,
    seConnecter: seConnecterMock,
    ouvrirSession: vi.fn(),
    seDeconnecter: vi.fn(),
  }),
}));

// Le canvas n'est pas implemente par jsdom : on remplace le composant par un
// bouton qui emet directement une signature factice.
vi.mock("@/components/signature-pad", () => ({
  SignaturePad: ({ onChange }: { onChange: (v: string | null) => void }) => (
    <button type="button" onClick={() => onChange("c2lnbmF0dXJl")}>
      Tracer une signature factice
    </button>
  ),
}));

const deciderMock = vi.fn();
const apercuDecisionMock = vi.fn();
const suspendreMock = vi.fn();
const listerMessagesMock = vi.fn();
const reprendreMock = vi.fn();
const telechargerPieceMock = vi.fn();
const historiqueMock = vi.fn();
vi.mock("@/lib/telechargement", () => ({ enregistrerFichier: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    decider: (...args: unknown[]) => deciderMock(...args),
    apercuDecision: (...args: unknown[]) => apercuDecisionMock(...args),
    suspendreDemande: (...args: unknown[]) => suspendreMock(...args),
    listerMessages: (...args: unknown[]) => listerMessagesMock(...args),
    reprendreDemande: (...args: unknown[]) => reprendreMock(...args),
    telechargerPieceJointe: (...args: unknown[]) => telechargerPieceMock(...args),
    historiqueDemande: (...args: unknown[]) => historiqueMock(...args),
  };
});

import DecisionPage from "./page";

const apercuConges = {
  action: "approuver",
  processus: "conges",
  est_derogation: false,
  demande_id: "demande-1",
  statut_demande: "en_cours",
  demandeur_nom: "Aïcha Bello",
  resume: { date_debut: "2026-06-01", date_fin: "2026-06-03" },
};

beforeEach(() => {
  vi.clearAllMocks();
  etatConnecte = true;
  listerMessagesMock.mockResolvedValue([]);
  historiqueMock.mockResolvedValue([]);
});

describe("DecisionPage — action portee par le jeton", () => {
  it("un jeton d'approbation n'affiche qu'un bouton d'approbation (pas de bouton Refuser trompeur)", async () => {
    apercuDecisionMock.mockResolvedValue(apercuConges);
    render(<DecisionPage />);

    expect(await screen.findByRole("button", { name: /confirmer l'approbation/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /refuser|confirmer le refus/i })).not.toBeInTheDocument();
    expect(screen.getByText(/du 2026-06-01 au 2026-06-03/i)).toBeInTheDocument();
  });

  it("approuver sans commentaire fonctionne et envoie les bonnes options", async () => {
    apercuDecisionMock.mockResolvedValue(apercuConges);
    deciderMock.mockResolvedValue({ demande_id: "d1", etape_id: "e1", action: "approuver", statut_global: "terminee" });
    render(<DecisionPage />);

    await userEvent.click(await screen.findByRole("button", { name: /confirmer l'approbation/i }));

    await waitFor(() => expect(screen.getByText(/demande approuvée/i)).toBeInTheDocument());
    expect(deciderMock).toHaveBeenCalledWith("jeton-test-123", {
      commentaire: undefined,
      signature_image_base64: undefined,
      justification_acceptation: undefined,
    });
  });

  it("un jeton de refus exige un commentaire, sans appeler l'API", async () => {
    apercuDecisionMock.mockResolvedValue({ ...apercuConges, action: "refuser" });
    render(<DecisionPage />);

    await userEvent.click(await screen.findByRole("button", { name: /confirmer le refus/i }));

    expect(await screen.findByText(/un commentaire est obligatoire en cas de refus/i)).toBeInTheDocument();
    expect(deciderMock).not.toHaveBeenCalled();
  });

  it("un jeton invalide affiche l'erreur et aucun formulaire", async () => {
    const { ApiError } = await import("@/lib/api");
    apercuDecisionMock.mockRejectedValue(new ApiError(401, "Jeton de décision invalide ou expiré."));
    render(<DecisionPage />);

    expect(await screen.findByText(/jeton de décision invalide ou expiré/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirmer/i })).not.toBeInTheDocument();
  });
});

describe("DecisionPage — signature et dérogation", () => {
  it("un jeton 'signer' exige une signature avant d'appeler l'API, puis l'envoie", async () => {
    apercuDecisionMock.mockResolvedValue({
      action: "signer",
      processus: "achats",
      est_derogation: false,
      demandeur_nom: "Karim Fofana",
      resume: { tiers: "Fournisseur X", budget_engage: 1200, objet: "Licences" },
    });
    deciderMock.mockResolvedValue({ demande_id: "d1", etape_id: "e1", action: "signer", statut_global: "terminee" });
    render(<DecisionPage />);

    const signer = await screen.findByRole("button", { name: /^signer$/i });
    await userEvent.click(signer);
    expect(await screen.findByText(/une signature est obligatoire/i)).toBeInTheDocument();
    expect(deciderMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /tracer une signature factice/i }));
    await userEvent.click(screen.getByRole("button", { name: /^signer$/i }));

    await waitFor(() => expect(screen.getByText(/document signé/i)).toBeInTheDocument());
    expect(deciderMock).toHaveBeenCalledWith(
      "jeton-test-123",
      expect.objectContaining({ signature_image_base64: "c2lnbmF0dXJl" })
    );
  });

  it("approuver une dérogation exige une justification d'acceptation", async () => {
    apercuDecisionMock.mockResolvedValue({
      action: "approuver",
      processus: "notes_frais",
      est_derogation: true,
      demandeur_nom: "Karim Fofana",
      resume: { montant: 500, categorie: "Matériel", date_depense: "2026-03-01", motif_derogation: "Urgent" },
    });
    deciderMock.mockResolvedValue({ demande_id: "d1", etape_id: "e1", action: "approuver", statut_global: "terminee" });
    render(<DecisionPage />);

    await userEvent.click(await screen.findByRole("button", { name: /confirmer l'approbation/i }));
    expect(await screen.findByText(/justification d'acceptation est obligatoire/i)).toBeInTheDocument();
    expect(deciderMock).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/justification d'acceptation/i), "Accepté, cas exceptionnel.");
    await userEvent.click(screen.getByRole("button", { name: /confirmer l'approbation/i }));

    await waitFor(() =>
      expect(deciderMock).toHaveBeenCalledWith(
        "jeton-test-123",
        expect.objectContaining({ justification_acceptation: "Accepté, cas exceptionnel." })
      )
    );
  });
});

describe("DecisionPage — connexion depuis la page de decision", () => {
  it("se connecter ici ne redirige jamais vers /mes-demandes (jeton de decision preserve)", async () => {
    apercuDecisionMock.mockResolvedValue(apercuConges);
    etatConnecte = false;
    const { rerender } = render(<DecisionPage />);

    expect(screen.getByLabelText("E-mail")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("E-mail"), "manager@test.tld");
    await userEvent.type(screen.getByLabelText("Mot de passe"), "motdepasse123");
    await userEvent.click(screen.getByRole("button", { name: /se connecter/i }));

    await waitFor(() => expect(seConnecterMock).toHaveBeenCalled());
    rerender(<DecisionPage />);

    expect(await screen.findByText(/décision — demande de congés/i)).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalledWith("/mes-demandes");
  });
});


describe("DecisionPage — communication bidirectionnelle (suspendre / discuter / reprendre)", () => {
  it("suspendre exige un message, puis bascule sur la discussion sans jamais décider", async () => {
    apercuDecisionMock.mockResolvedValueOnce(apercuConges).mockResolvedValue({
      ...apercuConges,
      statut_demande: "complement_demande",
    });
    suspendreMock.mockResolvedValue({});
    render(<DecisionPage />);

    await userEvent.click(await screen.findByRole("button", { name: /demander des précisions au demandeur/i }));
    await userEvent.click(screen.getByRole("button", { name: /suspendre et demander des précisions/i }));
    expect(await screen.findByText(/décrivez les précisions attendues/i)).toBeInTheDocument();
    expect(suspendreMock).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText("Précisions attendues"), "Justificatif illisible.");
    await userEvent.click(screen.getByRole("button", { name: /suspendre et demander des précisions/i }));

    await waitFor(() => expect(suspendreMock).toHaveBeenCalledWith("demande-1", "Justificatif illisible."));
    expect(await screen.findByText(/en attente de précisions/i)).toBeInTheDocument();
    // La decision elle-meme n'a jamais ete envoyee, et son formulaire a disparu.
    expect(deciderMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /confirmer l'approbation/i })).not.toBeInTheDocument();
  });

  it("une demande déjà suspendue affiche la discussion, et la reprise ramène au formulaire de décision", async () => {
    apercuDecisionMock
      .mockResolvedValueOnce({ ...apercuConges, statut_demande: "complement_demande" })
      .mockResolvedValue(apercuConges);
    listerMessagesMock.mockResolvedValue([
      { id: "m1", auteur_id: "u", auteur_nom: "Aïcha Bello", contenu: "Voici la version lisible.", cree_le: "2026-06-01T10:00:00Z" },
    ]);
    reprendreMock.mockResolvedValue({ id: "demande-1", statut_global: "en_cours" });
    render(<DecisionPage />);

    expect(await screen.findByText("Voici la version lisible.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirmer l'approbation/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /reprendre le workflow/i }));

    await waitFor(() => expect(reprendreMock).toHaveBeenCalledWith("demande-1"));
    expect(await screen.findByRole("button", { name: /confirmer l'approbation/i })).toBeInTheDocument();
  });

  it("une demande annulée par le demandeur n'affiche aucun formulaire de décision ni de discussion", async () => {
    apercuDecisionMock.mockResolvedValue({ ...apercuConges, statut_demande: "annulee" });
    render(<DecisionPage />);

    expect(await screen.findByText(/annulée par le demandeur/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirmer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /demander des précisions/i })).not.toBeInTheDocument();
    expect(listerMessagesMock).not.toHaveBeenCalled();
  });

  it("montre le solde budgétaire au décideur, en vert quand l'enveloppe suffit (CDC 4.3)", async () => {
    apercuDecisionMock.mockResolvedValue({
      ...apercuConges,
      processus: "notes_frais",
      resume: { montant: 300, categorie: "Matériel", date_depense: "2026-03-01" },
      budget: { service: "Ventes", exercice: 2026, solde_disponible: 1000, montant_demande: 300, solde_apres_validation: 700, devise: "EUR" },
    });
    render(<DecisionPage />);

    const bloc = await screen.findByRole("group", { name: "Budget du service" });
    expect(bloc).toHaveTextContent("Enveloppe suffisante");
    expect(bloc).toHaveTextContent("Solde disponible : 1 000,00 €");
    expect(bloc).toHaveTextContent("Solde après validation : 700,00 €");
    expect(bloc).toHaveClass("bg-accent-soft");
  });

  it("affiche le montant dans sa devise d'origine avec l'équivalent, jamais « € » en dur (note en USD)", async () => {
    apercuDecisionMock.mockResolvedValue({
      ...apercuConges,
      processus: "notes_frais",
      resume: {
        montant: 800, devise: "USD", montant_reference: 736, categorie: "Voyage", date_depense: "2026-03-01",
        motif_derogation: "Mission urgente",
      },
      est_derogation: true,
      budget: { service: "Ventes", exercice: 2026, solde_disponible: 100, montant_demande: 736, solde_apres_validation: -636, devise: "EUR" },
    });
    render(<DecisionPage />);

    expect(await screen.findByText(/800,00 \$US \(≈ 736,00 €\) — Voyage/)).toBeInTheDocument();
    expect(screen.getByText("Motif de dérogation : Mission urgente")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Budget du service" })).toHaveTextContent("Dépassement de l'enveloppe");
  });

  it("achat en XAF : le montant garde sa devise et la référence apparaît en équivalent", async () => {
    apercuDecisionMock.mockResolvedValue({
      ...apercuConges,
      processus: "achats",
      resume: { tiers: "Fournisseur Douala", objet: "Serveurs", budget_engage: 3000000, devise: "XAF", budget_engage_reference: 4573.28 },
      budget: { service: "Ventes", exercice: 2026, solde_disponible: 10000, montant_demande: 4573.28, solde_apres_validation: 5426.72, devise: "EUR" },
    });
    render(<DecisionPage />);

    expect(await screen.findByText(/Fournisseur Douala — .*FCFA.*≈ 4 573,28 €/)).toBeInTheDocument();
  });

  it("signale un dépassement en rouge, sans le masquer", async () => {
    apercuDecisionMock.mockResolvedValue({
      ...apercuConges,
      processus: "achats",
      resume: { tiers: "X", budget_engage: 500 },
      budget: { service: "Ventes", exercice: 2026, solde_disponible: 100, montant_demande: 500, solde_apres_validation: -400, devise: "EUR" },
    });
    render(<DecisionPage />);

    const bloc = await screen.findByRole("group", { name: "Budget du service" });
    expect(bloc).toHaveTextContent("Dépassement de l'enveloppe");
    expect(bloc).toHaveTextContent("Solde après validation : -400,00 €");
    expect(bloc).toHaveClass("bg-danger-soft");
  });

  it("n'affiche aucun bloc budget pour une demande de congés", async () => {
    apercuDecisionMock.mockResolvedValue({ ...apercuConges, budget: null });
    render(<DecisionPage />);

    await screen.findByRole("button", { name: /confirmer l'approbation/i });
    expect(screen.queryByRole("group", { name: "Budget du service" })).not.toBeInTheDocument();
  });

  it("l'approbateur voit les pièces du dossier et peut les télécharger depuis la page de décision", async () => {
    apercuDecisionMock.mockResolvedValue({
      ...apercuConges,
      processus: "notes_frais",
      resume: { montant: 80, categorie: "Repas", date_depense: "2026-03-01" },
      pieces_jointes: [{ id: "p1", nom: "facture-restaurant.pdf", categorie: "recu" }],
    });
    telechargerPieceMock.mockResolvedValue(new Blob(["x"]));
    render(<DecisionPage />);

    await userEvent.click(await screen.findByRole("button", { name: /facture-restaurant\.pdf/ }));

    await waitFor(() => expect(telechargerPieceMock).toHaveBeenCalledWith("demande-1", "p1"));
    expect(screen.queryByLabelText(/ajouter une pièce/i)).not.toBeInTheDocument(); // consultation seule
  });

  it("aucune section de pièces quand le dossier n'en a pas", async () => {
    apercuDecisionMock.mockResolvedValue({ ...apercuConges, pieces_jointes: [] });
    render(<DecisionPage />);

    await screen.findByRole("button", { name: /confirmer l'approbation/i });
    expect(screen.queryByText("Pièces jointes")).not.toBeInTheDocument();
  });

  it("l'approbateur voit l'historique du dossier : ce que le niveau précédent a décidé, et pourquoi", async () => {
    apercuDecisionMock.mockResolvedValue({ ...apercuConges, processus: "notes_frais", resume: { montant: 800, categorie: "Matériel", date_depense: "2026-03-01" } });
    historiqueMock.mockResolvedValue([
      { horodate_le: "2026-06-01T10:00:00Z", action: "etape_approuvee", libelle: "Étape approuvée", acteur_nom: "Marie Manager", detail: "Commentaire : validé, montant justifié" },
    ]);
    render(<DecisionPage />);

    expect(await screen.findByText(/historique du dossier \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText("Commentaire : validé, montant justifié")).toBeInTheDocument();
    expect(historiqueMock).toHaveBeenCalledWith("demande-1");
  });
});
