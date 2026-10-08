// @vitest-environment node
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "./route";

const fetchMock = vi.fn();

/** Faux JWT dont seule la charge utile (exp) compte pour le proxy. */
function jwt(expDansSecondes: number) {
  const charge = Buffer.from(JSON.stringify({ sub: "u1", exp: Math.floor(Date.now() / 1000) + expDansSecondes })).toString("base64url");
  return `entete.${charge}.signature`;
}
const ACCES = jwt(2700);
const REFRESH = jwt(14 * 86400);

const backendJson = (corps: unknown, status = 200, extra: Record<string, string> = {}) =>
  new Response(JSON.stringify(corps), { status, headers: { "content-type": "application/json", ...extra } });

function requete(chemin: string, init: { method?: string; body?: unknown; cookie?: string; headers?: Record<string, string> } = {}) {
  const entetes: Record<string, string> = { "content-type": "application/json", ...(init.headers ?? {}) };
  if (init.cookie) entetes.cookie = init.cookie;
  return new NextRequest(`http://localhost:3000/api/backend/${chemin}`, {
    method: init.method ?? "GET",
    headers: entetes,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
}
const params = (chemin: string) => ({ params: Promise.resolve({ path: chemin.split("/") }) });
const cookiesPoses = (r: Response) => r.headers.getSetCookie();
const cookie = (r: Response, nom: string) => cookiesPoses(r).find((c) => c.startsWith(`${nom}=`)) ?? "";

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("COOKIE_SECURE", "true");
});
afterEach(() => vi.unstubAllEnvs());

describe("connexion : les jetons deviennent des cookies httpOnly", () => {
  const CHEMIN = "api/v1/auth/login";
  const reussite = () => backendJson({ access_token: ACCES, refresh_token: REFRESH, token_type: "bearer" });

  it("la réponse ne contient AUCUN jeton, seulement { connecte: true }", async () => {
    fetchMock.mockResolvedValueOnce(reussite());

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: { email: "a@b.c", mot_de_passe: "x" } }), params(CHEMIN));

    expect(reponse.status).toBe(200);
    const texte = await reponse.text();
    expect(JSON.parse(texte)).toEqual({ connecte: true });
    expect(texte).not.toContain(ACCES);
    expect(texte).not.toContain(REFRESH);
    expect(texte).not.toMatch(/token/i);
  });

  it("le cookie d'accès est httpOnly, Secure, SameSite=Strict, limité à /api/backend", async () => {
    fetchMock.mockResolvedValueOnce(reussite());

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    const c = cookie(reponse, "wf_access");
    expect(c).toContain(`wf_access=${ACCES}`);
    expect(c).toMatch(/HttpOnly/i);
    expect(c).toMatch(/Secure/i);
    expect(c).toMatch(/SameSite=strict/i);
    expect(c).toContain("Path=/api/backend");
    expect(c).not.toContain("Path=/api/backend/api");
  });

  it("le cookie de rafraîchissement est restreint au seul chemin /auth/refresh (aucun autre appel ne le reçoit)", async () => {
    fetchMock.mockResolvedValueOnce(reussite());

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    const c = cookie(reponse, "wf_refresh");
    expect(c).toMatch(/HttpOnly/i);
    expect(c).toMatch(/SameSite=strict/i);
    expect(c).toContain("Path=/api/backend/api/v1/auth/refresh");
    expect(c).not.toMatch(/Path=\/api\/backend\/api\/v1\/auth;/);
  });

  it("les cookies expirent en même temps que les jetons (durée lue dans le champ exp)", async () => {
    fetchMock.mockResolvedValueOnce(reussite());

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    const maxAge = (c: string) => Number(/Max-Age=(\d+)/i.exec(c)?.[1]);
    expect(maxAge(cookie(reponse, "wf_access"))).toBeGreaterThan(2600);
    expect(maxAge(cookie(reponse, "wf_access"))).toBeLessThanOrEqual(2700);
    expect(maxAge(cookie(reponse, "wf_refresh"))).toBeGreaterThan(13 * 86400);
  });

  it("un jeton illisible retombe sur une durée par défaut au lieu de planter", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ access_token: "pas-un-jwt", refresh_token: "non-plus", token_type: "bearer" }));

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    expect(reponse.status).toBe(200);
    expect(Number(/Max-Age=(\d+)/i.exec(cookie(reponse, "wf_access"))?.[1])).toBe(45 * 60);
  });

  it("COOKIE_SECURE=false retire l'attribut Secure (développement en HTTP)", async () => {
    vi.stubEnv("COOKIE_SECURE", "false");
    fetchMock.mockResolvedValueOnce(reussite());

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    expect(cookie(reponse, "wf_access")).not.toMatch(/Secure/i);
    expect(cookie(reponse, "wf_access")).toMatch(/HttpOnly/i); // httpOnly reste toujours actif
  });

  it("un échec de connexion est relayé tel quel et ne pose AUCUN cookie", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ detail: "Identifiants invalides." }, 401));

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    expect(reponse.status).toBe(401);
    expect((await reponse.json()).detail).toBe("Identifiants invalides.");
    expect(cookiesPoses(reponse)).toEqual([]);
  });

  it("le verrouillage de compte (429) conserve son en-tête Retry-After", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ detail: "Trop de tentatives." }, 429, { "retry-after": "900" }));

    const reponse = await POST(requete(CHEMIN, { method: "POST", body: {} }), params(CHEMIN));

    expect(reponse.status).toBe(429);
    expect(reponse.headers.get("retry-after")).toBe("900");
  });

  it("l'activation de compte (définir le mot de passe) ouvre aussi la session par cookies", async () => {
    const chemin = "api/v1/auth/definir-mot-de-passe";
    fetchMock.mockResolvedValueOnce(reussite());

    const reponse = await POST(requete(chemin, { method: "POST", body: { jeton: "j", mot_de_passe: "x" } }), params(chemin));

    expect(await reponse.json()).toEqual({ connecte: true });
    expect(cookie(reponse, "wf_access")).toContain(ACCES);
  });

  it("le corps de la requête est transmis au backend", async () => {
    fetchMock.mockResolvedValueOnce(reussite());

    await POST(requete(CHEMIN, { method: "POST", body: { email: "a@b.c", mot_de_passe: "secret" } }), params(CHEMIN));

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8000/api/v1/auth/login");
    expect(JSON.parse(options.body)).toEqual({ email: "a@b.c", mot_de_passe: "secret" });
  });
});

describe("appels métier : le cookie d'accès devient un en-tête Authorization côté serveur", () => {
  it("injecte Authorization: Bearer <cookie> quand le navigateur n'envoie aucun en-tête", async () => {
    fetchMock.mockResolvedValueOnce(backendJson([]));

    await GET(requete("api/v1/conges/moi", { cookie: `wf_access=${ACCES}` }), params("api/v1/conges/moi"));

    expect(fetchMock.mock.calls[0][1].headers.get("authorization")).toBe(`Bearer ${ACCES}`);
  });

  it("sans cookie ni en-tête : aucune autorisation n'est inventée", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ detail: "Non authentifié" }, 401));

    const reponse = await GET(requete("api/v1/conges/moi"), params("api/v1/conges/moi"));

    expect(fetchMock.mock.calls[0][1].headers.get("authorization")).toBeNull();
    expect(reponse.status).toBe(401);
  });

  it("un en-tête Authorization explicite (script, test) reste prioritaire sur le cookie", async () => {
    fetchMock.mockResolvedValueOnce(backendJson([]));

    await GET(
      requete("api/v1/conges/moi", { cookie: `wf_access=${ACCES}`, headers: { authorization: "Bearer explicite" } }),
      params("api/v1/conges/moi")
    );

    expect(fetchMock.mock.calls[0][1].headers.get("authorization")).toBe("Bearer explicite");
  });

  it("le cookie de rafraîchissement n'est jamais transmis au backend avec un appel métier", async () => {
    fetchMock.mockResolvedValueOnce(backendJson([]));

    await GET(requete("api/v1/conges/moi", { cookie: `wf_access=${ACCES}; wf_refresh=${REFRESH}` }), params("api/v1/conges/moi"));

    expect(fetchMock.mock.calls[0][1].headers.get("cookie")).toBeNull();
    expect(JSON.stringify([...fetchMock.mock.calls[0][1].headers.entries()])).not.toContain(REFRESH);
  });

  it("une réponse binaire (PDF) traverse le proxy intacte", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(new Uint8Array([37, 80, 68, 70]), {
        status: 200,
        headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="BC-2026-0001.pdf"' },
      })
    );

    const reponse = await GET(requete("api/v1/achats/a1/bon-commande", { cookie: `wf_access=${ACCES}` }), params("api/v1/achats/a1/bon-commande"));

    expect(reponse.headers.get("content-type")).toBe("application/pdf");
    expect(reponse.headers.get("content-disposition")).toContain("BC-2026-0001.pdf");
    expect(new Uint8Array(await reponse.arrayBuffer())).toEqual(new Uint8Array([37, 80, 68, 70]));
  });
});

describe("renouvellement de session", () => {
  const CHEMIN = "api/v1/auth/refresh";

  it("lit le jeton de rafraîchissement dans le cookie (jamais dans la requête du navigateur) et pose de nouveaux cookies", async () => {
    const nouvelAcces = jwt(2700);
    const nouveauRefresh = jwt(14 * 86400);
    fetchMock.mockResolvedValueOnce(backendJson({ access_token: nouvelAcces, refresh_token: nouveauRefresh, token_type: "bearer" }));

    const reponse = await POST(requete(CHEMIN, { method: "POST", cookie: `wf_refresh=${REFRESH}` }), params(CHEMIN));

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ refresh_token: REFRESH });
    expect(await reponse.json()).toEqual({ connecte: true });
    expect(cookie(reponse, "wf_access")).toContain(nouvelAcces);
    expect(cookie(reponse, "wf_refresh")).toContain(nouveauRefresh); // le refresh est tournant
  });

  it("sans cookie de rafraîchissement : 401 immédiat, le backend n'est pas appelé", async () => {
    const reponse = await POST(requete(CHEMIN, { method: "POST" }), params(CHEMIN));

    expect(reponse.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ignore tout jeton placé dans le corps de la requête (seul le cookie fait foi)", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ access_token: ACCES, refresh_token: REFRESH, token_type: "bearer" }));

    await POST(
      requete(CHEMIN, { method: "POST", cookie: `wf_refresh=${REFRESH}`, body: { refresh_token: "injecte-par-le-navigateur" } }),
      params(CHEMIN)
    );

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ refresh_token: REFRESH });
  });

  it("refresh refusé (401) : la session est terminée, les deux cookies sont effacés", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ detail: "Jeton expiré" }, 401));

    const reponse = await POST(requete(CHEMIN, { method: "POST", cookie: `wf_refresh=${REFRESH}` }), params(CHEMIN));

    expect(reponse.status).toBe(401);
    expect(cookie(reponse, "wf_access")).toMatch(/Max-Age=0/i);
    expect(cookie(reponse, "wf_refresh")).toMatch(/Max-Age=0/i);
  });

  it("panne du backend (500) : les cookies sont CONSERVÉS pour pouvoir réessayer", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ detail: "Erreur" }, 500));

    const reponse = await POST(requete(CHEMIN, { method: "POST", cookie: `wf_refresh=${REFRESH}` }), params(CHEMIN));

    expect(reponse.status).toBe(500);
    expect(cookiesPoses(reponse)).toEqual([]);
  });
});

describe("déconnexion", () => {
  const CHEMIN = "api/v1/auth/deconnexion";

  it("efface les deux cookies avec les MÊMES chemins que ceux de la connexion, sans appeler le backend", async () => {
    const reponse = await POST(requete(CHEMIN, { method: "POST", cookie: `wf_access=${ACCES}; wf_refresh=${REFRESH}` }), params(CHEMIN));

    expect(await reponse.json()).toEqual({ connecte: false });
    expect(fetchMock).not.toHaveBeenCalled();
    const acces = cookie(reponse, "wf_access");
    const refresh = cookie(reponse, "wf_refresh");
    expect(acces).toMatch(/Max-Age=0/i);
    expect(refresh).toMatch(/Max-Age=0/i);
    // Un cookie ne s'efface que s'il est visé avec le même chemin que celui qui l'a posé.
    expect(acces).toContain("Path=/api/backend");
    expect(refresh).toContain("Path=/api/backend/api/v1/auth/refresh");
    expect(acces).toMatch(/HttpOnly/i);
  });

  it("la déconnexion n'est acceptée qu'en POST (un simple lien ne peut pas déconnecter)", async () => {
    fetchMock.mockResolvedValueOnce(backendJson({ detail: "Not Found" }, 404));

    const reponse = await GET(requete(CHEMIN), params(CHEMIN));

    expect(reponse.status).toBe(404); // relayé au backend comme n'importe quelle route inconnue
    expect(cookiesPoses(reponse)).toEqual([]);
  });
});
