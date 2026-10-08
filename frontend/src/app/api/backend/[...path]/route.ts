import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy generique vers le backend FastAPI.
 *
 * Amelioration reelle par rapport au mecanisme Vite (window.__ENV__ /
 * env-config.js genere par docker-entrypoint.sh au demarrage du conteneur) :
 * process.env.API_BASE_URL est lu ici cote serveur, a CHAQUE requete, sans
 * jamais etre inline dans un bundle JS envoye au navigateur. Changer l'URL
 * du backend ne demande donc ni rebuild, ni script d'entrypoint dedie -
 * juste une variable d'environnement sur le conteneur Next.js.
 *
 * Consequence secondaire utile : le navigateur ne connait jamais l'adresse
 * reelle du backend (appels toujours en meme origine, /api/backend/...),
 * ce qui evite aussi toute configuration CORS cote FastAPI.
 */

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * Session par cookies httpOnly (correction R23).
 *
 * Avant : le navigateur recevait les jetons JWT dans le corps de la reponse de connexion et les gardait
 * dans localStorage, lisible par tout script de la page - une faille XSS suffisait a les voler.
 * Maintenant : ce proxy intercepte la connexion, place les jetons dans des cookies `httpOnly` (invisibles
 * du JavaScript), et les reinjecte lui-meme dans l'en-tete Authorization des appels suivants. Le JS du
 * navigateur ne voit plus jamais un jeton. Le backend FastAPI n'est pas modifie.
 *
 * - `wf_access`  : jeton d'acces, envoye a tout /api/backend ;
 * - `wf_refresh` : jeton de rafraichissement, restreint au seul chemin /api/backend/api/v1/auth/refresh :
 *   le navigateur ne l'envoie a aucun autre appel. Et meme la, le proxy ne le transmet jamais tel quel au
 *   backend (seul l'en-tete Authorization est relaye) ;
 * - SameSite=Strict : un site tiers ne peut pas declencher d'action avec la session de l'utilisateur
 *   (protection CSRF). Le lien recu par e-mail reste utilisable : la page de decision est chargee sans
 *   cookie, puis ses appels a l'API partent de notre propre site, cookies inclus.
 */
const COOKIE_ACCES = "wf_access";
const COOKIE_RAFRAICHISSEMENT = "wf_refresh";
const CHEMIN_COOKIE_ACCES = "/api/backend";
const CHEMIN_COOKIE_RAFRAICHISSEMENT = "/api/backend/api/v1/auth/refresh";
const DUREE_ACCES_PAR_DEFAUT = 45 * 60;
const DUREE_RAFRAICHISSEMENT_PAR_DEFAUT = 14 * 24 * 60 * 60;

const CHEMIN_LOGIN = "api/v1/auth/login";
const CHEMIN_ACTIVATION = "api/v1/auth/definir-mot-de-passe";
const CHEMIN_REFRESH = "api/v1/auth/refresh";
const CHEMIN_DECONNEXION = "api/v1/auth/deconnexion"; // propre au proxy : n'existe pas cote backend

type Jetons = { access_token: string; refresh_token: string };

function cookieSecurise(): boolean {
  const force = process.env.COOKIE_SECURE;
  if (force !== undefined) return force === "true";
  return process.env.NODE_ENV === "production";
}

/** Duree de vie restante d'un JWT (champ exp), pour que le cookie expire en meme temps que lui. */
function dureeRestante(jeton: string, parDefaut: number): number {
  try {
    const charge = JSON.parse(Buffer.from(jeton.split(".")[1], "base64url").toString("utf-8"));
    const restant = Number(charge.exp) - Math.floor(Date.now() / 1000);
    if (Number.isFinite(restant) && restant > 0) return restant;
  } catch {
    // jeton illisible : duree par defaut
  }
  return parDefaut;
}

function poserCookies(reponse: NextResponse, jetons: Jetons) {
  const commun = { httpOnly: true, sameSite: "strict" as const, secure: cookieSecurise() };
  reponse.cookies.set(COOKIE_ACCES, jetons.access_token, {
    ...commun,
    path: CHEMIN_COOKIE_ACCES,
    maxAge: dureeRestante(jetons.access_token, DUREE_ACCES_PAR_DEFAUT),
  });
  reponse.cookies.set(COOKIE_RAFRAICHISSEMENT, jetons.refresh_token, {
    ...commun,
    path: CHEMIN_COOKIE_RAFRAICHISSEMENT,
    maxAge: dureeRestante(jetons.refresh_token, DUREE_RAFRAICHISSEMENT_PAR_DEFAUT),
  });
}

function effacerCookies(reponse: NextResponse) {
  const commun = { httpOnly: true, sameSite: "strict" as const, secure: cookieSecurise(), maxAge: 0 };
  reponse.cookies.set(COOKIE_ACCES, "", { ...commun, path: CHEMIN_COOKIE_ACCES });
  reponse.cookies.set(COOKIE_RAFRAICHISSEMENT, "", { ...commun, path: CHEMIN_COOKIE_RAFRAICHISSEMENT });
}

/** Reponse sans aucun jeton : le navigateur sait seulement que la session est ouverte. */
function sessionOuverte(jetons: Jetons): NextResponse {
  const reponse = NextResponse.json({ connecte: true });
  poserCookies(reponse, jetons);
  return reponse;
}

function erreurRelayee(corps: ArrayBuffer, reponse: Response): NextResponse {
  const entetes = new Headers();
  const type = reponse.headers.get("content-type");
  if (type) entetes.set("content-type", type);
  const retryAfter = reponse.headers.get("retry-after");
  if (retryAfter) entetes.set("retry-after", retryAfter); // verrouillage de compte (429)
  return new NextResponse(corps, { status: reponse.status, headers: entetes });
}

async function appelerBackend(chemin: string, corps: string, typeContenu = "application/json") {
  return fetch(new URL(`${API_BASE_URL}/${chemin}`), {
    method: "POST",
    headers: { "content-type": typeContenu },
    body: corps,
    cache: "no-store",
  });
}

/** Connexion et activation de compte : le backend renvoie des jetons, on les convertit en cookies. */
async function ouvrirSession(request: NextRequest, chemin: string): Promise<NextResponse> {
  const reponse = await appelerBackend(
    chemin,
    await request.text(),
    request.headers.get("content-type") ?? "application/json"
  );
  const corps = await reponse.arrayBuffer();
  if (!reponse.ok) return erreurRelayee(corps, reponse);
  return sessionOuverte(JSON.parse(new TextDecoder().decode(corps)) as Jetons);
}

/** Renouvellement : le jeton de rafraichissement vient du cookie, jamais du navigateur. */
async function renouvelerSession(request: NextRequest): Promise<NextResponse> {
  const refresh = request.cookies.get(COOKIE_RAFRAICHISSEMENT)?.value;
  if (!refresh) {
    return NextResponse.json({ detail: "Aucune session à renouveler." }, { status: 401 });
  }
  const reponse = await appelerBackend(CHEMIN_REFRESH, JSON.stringify({ refresh_token: refresh }));
  const corps = await reponse.arrayBuffer();
  if (!reponse.ok) {
    const erreur = erreurRelayee(corps, reponse);
    if (reponse.status === 401) effacerCookies(erreur); // refresh invalide ou expire : session terminee
    return erreur;
  }
  return sessionOuverte(JSON.parse(new TextDecoder().decode(corps)) as Jetons);
}

function fermerSession(): NextResponse {
  const reponse = NextResponse.json({ connecte: false });
  effacerCookies(reponse);
  return reponse;
}

async function relayer(request: NextRequest, segments: string[]) {
  // Le slash final est significatif cote FastAPI (voir next.config.ts,
  // skipTrailingSlashRedirect) : `params.path` ne le conserve pas
  // toujours, on le relit donc sur l'URL d'origine.
  const chemin = segments.filter(Boolean).join("/");

  if (request.method === "POST") {
    if (chemin === CHEMIN_LOGIN || chemin === CHEMIN_ACTIVATION) return ouvrirSession(request, chemin);
    if (chemin === CHEMIN_REFRESH) return renouvelerSession(request);
    if (chemin === CHEMIN_DECONNEXION) return fermerSession();
  }

  const slashFinal = request.nextUrl.pathname.endsWith("/") ? "/" : "";
  const url = new URL(`${API_BASE_URL}/${chemin}${slashFinal}`);
  url.search = request.nextUrl.search;

  const entetes = new Headers();
  // Le jeton d'acces vient du cookie httpOnly. Un en-tete Authorization explicite (script, test) reste
  // accepte tel quel ; le navigateur, lui, n'en envoie plus jamais.
  const autorisation = request.headers.get("authorization");
  const jetonCookie = request.cookies.get(COOKIE_ACCES)?.value;
  if (autorisation) entetes.set("authorization", autorisation);
  else if (jetonCookie) entetes.set("authorization", `Bearer ${jetonCookie}`);
  const typeContenu = request.headers.get("content-type");
  if (typeContenu) entetes.set("content-type", typeContenu);

  const corps =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  const reponse = await fetch(url, {
    method: request.method,
    headers: entetes,
    body: corps,
    // Pas de cache : chaque appel doit atteindre reellement le backend
    // (donnees de workflow, jamais statiques).
    cache: "no-store",
  });

  // Passthrough binaire (ex. fiche de confirmation PDF, section 12 du CDC) -
  // pas de parsing JSON intermediaire qui casserait un flux non-JSON.
  const corpsReponse = await reponse.arrayBuffer();
  const entetesReponse = new Headers();
  const typeContenuReponse = reponse.headers.get("content-type");
  if (typeContenuReponse) entetesReponse.set("content-type", typeContenuReponse);
  const dispositionReponse = reponse.headers.get("content-disposition");
  if (dispositionReponse) entetesReponse.set("content-disposition", dispositionReponse);
  const retryAfterReponse = reponse.headers.get("retry-after");
  if (retryAfterReponse) entetesReponse.set("retry-after", retryAfterReponse);

  return new NextResponse(corpsReponse, {
    status: reponse.status,
    headers: entetesReponse,
  });
}

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return relayer(request, path);
}
export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return relayer(request, path);
}
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return relayer(request, path);
}
export async function PUT(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return relayer(request, path);
}
export async function DELETE(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return relayer(request, path);
}
