import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  EVENEMENT_SESSION_EXPIREE,
  ApiError,
  deconnecter,
  definirMotDePasse,
  listerMesDemandesConges,
  login,
  sessionProbable,
  soumettreDemandeAchat,
  telechargerContratAchat,
} from "./api";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

const json = (corps: unknown, status = 200) =>
  new Response(JSON.stringify(corps), { status, headers: { "content-type": "application/json" } });

const SESSION_OUVERTE = { connecte: true };

beforeEach(() => {
  fetchMock.mockReset();
  localStorage.clear();
  // Indicateur non sensible : les jetons eux-memes sont dans des cookies httpOnly (R23).
  localStorage.setItem("workflows.session", "1");
});

describe("renouvellement de session (jeton d'accès expiré)", () => {
  it("sur 401 : renouvelle via /auth/refresh SANS corps (le jeton est dans un cookie httpOnly) puis rejoue la requête", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Jeton expiré" }, 401))
      .mockResolvedValueOnce(json(SESSION_OUVERTE))
      .mockResolvedValueOnce(json([{ id: "d1" }]));

    const resultat = await listerMesDemandesConges();

    expect(resultat).toEqual([{ id: "d1" }]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/backend/api/v1/auth/refresh");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    expect(fetchMock.mock.calls[1][1].body).toBeUndefined();
  });

  it("aucun appel n'expose de jeton : pas d'en-tête Authorization, pas de jeton dans le stockage du navigateur", async () => {
    fetchMock.mockResolvedValue(json([]));

    await listerMesDemandesConges();

    for (const appel of fetchMock.mock.calls) {
      expect(appel[1].headers?.Authorization).toBeUndefined();
    }
    const contenuStockage = JSON.stringify(Object.entries(localStorage));
    expect(contenuStockage).not.toMatch(/access|refresh|token|jeton/i);
  });

  it("si le renouvellement échoue : indicateur effacé, événement émis, l'erreur 401 remonte", async () => {
    const surExpiration = vi.fn();
    window.addEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Jeton expiré" }, 401))
      .mockResolvedValueOnce(json({ detail: "Refresh expiré" }, 401));

    await expect(listerMesDemandesConges()).rejects.toMatchObject({ status: 401 });

    expect(sessionProbable()).toBe(false);
    expect(surExpiration).toHaveBeenCalledTimes(1);
    window.removeEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
  });

  it("visiteur anonyme (aucun indicateur) : un 401 ne déclenche ni renouvellement ni événement", async () => {
    localStorage.clear();
    const surExpiration = vi.fn();
    window.addEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
    fetchMock.mockResolvedValueOnce(json({ detail: "Non authentifié" }, 401));

    await expect(listerMesDemandesConges()).rejects.toMatchObject({ status: 401 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(surExpiration).not.toHaveBeenCalled();
    window.removeEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
  });

  it("une connexion refusée (401 sans authentification) ne déclenche aucun renouvellement", async () => {
    localStorage.clear();
    fetchMock.mockResolvedValueOnce(json({ detail: "Identifiants invalides" }, 401));

    await expect(login("a@b.c", "mauvais")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sessionProbable()).toBe(false); // un échec de connexion n'ouvre pas de session
  });

  it("plusieurs appels simultanés expirés partagent UN SEUL renouvellement (le refresh est tournant)", async () => {
    let refreshs = 0;
    let renouvele = false;
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/auth/refresh")) {
        refreshs += 1;
        await new Promise((r) => setTimeout(r, 10));
        renouvele = true;
        return json(SESSION_OUVERTE);
      }
      return renouvele ? json([]) : json({ detail: "expiré" }, 401);
    });

    const resultats = await Promise.all([
      listerMesDemandesConges(),
      listerMesDemandesConges(),
      listerMesDemandesConges(),
    ]);

    expect(resultats).toEqual([[], [], []]);
    expect(refreshs).toBe(1);
  });

  it("l'envoi multipart (achats) est rejoué avec son fichier après renouvellement", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ detail: "expiré" }, 401))
      .mockResolvedValueOnce(json(SESSION_OUVERTE))
      .mockResolvedValueOnce(json({ id: "a1", statut_global: "en_cours", premiere_etape_id: "e", derogation: false }, 201));
    const fichier = new File(["%PDF"], "contrat.pdf", { type: "application/pdf" });

    const resultat = await soumettreDemandeAchat({
      tiers: "X",
      objet: "Y",
      budget_engage: 10,
      derogation_motivee: false,
      fichier_contrat: fichier,
    });

    expect(resultat.id).toBe("a1");
    const premier = fetchMock.mock.calls[0][1].body as FormData;
    const rejoue = fetchMock.mock.calls[2][1].body as FormData;
    expect((rejoue.get("fichier_contrat") as File).name).toBe("contrat.pdf");
    expect(rejoue).toBe(premier);
  });

  it("un téléchargement de fichier est lui aussi renouvelé", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ detail: "expiré" }, 401))
      .mockResolvedValueOnce(json(SESSION_OUVERTE))
      .mockResolvedValueOnce(new Response("contenu", { status: 200 }));

    const blob = await telechargerContratAchat("a1");

    expect(await blob.text()).toBe("contenu");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe("ouverture et fermeture de session (R23)", () => {
  it("la connexion réussie marque la session ; la réponse ne contient aucun jeton", async () => {
    localStorage.clear();
    fetchMock.mockResolvedValueOnce(json(SESSION_OUVERTE));

    const reponse = await login("a@b.c", "secret");

    expect(reponse).toEqual(SESSION_OUVERTE);
    expect(sessionProbable()).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/backend/api/v1/auth/login");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ email: "a@b.c", mot_de_passe: "secret" });
  });

  it("l'activation de compte (lien d'invitation) ouvre aussi la session", async () => {
    localStorage.clear();
    fetchMock.mockResolvedValueOnce(json(SESSION_OUVERTE));

    await definirMotDePasse("jeton-lien", "MotDePasse123!");

    expect(sessionProbable()).toBe(true);
  });

  it("la déconnexion appelle le proxy (qui efface les cookies) puis efface l'indicateur", async () => {
    fetchMock.mockResolvedValueOnce(json({ connecte: false }));

    await deconnecter();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/backend/api/v1/auth/deconnexion");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(sessionProbable()).toBe(false);
  });

  it("la déconnexion efface l'indicateur même si le réseau échoue", async () => {
    fetchMock.mockRejectedValueOnce(new Error("réseau coupé"));

    await expect(deconnecter()).rejects.toThrow();

    expect(sessionProbable()).toBe(false);
  });
});
