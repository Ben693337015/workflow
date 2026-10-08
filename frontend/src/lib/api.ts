/**
 * Client API pour le backend FastAPI - porte depuis le frontend Vite.
 *
 * Ecart avec la version Vite (documente dans le proxy, voir
 * app/api/backend/[...path]/route.ts) : BASE_URL n'est plus une URL externe
 * du backend a connaitre au build ou a injecter au runtime cote navigateur
 * (window.__ENV__) - c'est toujours ce meme chemin relatif, /api/backend,
 * qui passe par le proxy Next.js. Le proxy, lui, lit l'URL reelle du
 * backend cote serveur au moment de chaque requete.
 */
import type {
  AgendaEquipeEvenement,
  ActionAudit,
  ApercuDecision,
  Conversion,
  DevisesReponse,
  AuditPage,
  DecisionResponse,
  DemandeAchat,
  DemandeConges,
  EnveloppeBudgetaire,
  HistoriqueEntree,
  JourFerie,
  LigneAchat,
  MessageClarification,
  NoteFrais,
  NoteFraisCreate,
  PieceJointe,
  RoleUtilisateur,
  SoldeCongesRead,
  RegularisationResponse,
  SoumissionAchatResponse,
  SyntheseFrais,
  TauxChange,
  SoumissionCongesResponse,
  SoumissionNotesFraisResponse,
  SessionResponse,
  TypeConge,
  UtilisateurModifie,
  UtilisateurRead,
} from "@/types";

const BASE_URL = "/api/backend";

/**
 * Session (correction R23) : les jetons ne sont PLUS accessibles au JavaScript. Ils vivent dans des cookies
 * httpOnly poses par le proxy Next.js (app/api/backend/[...path]/route.ts), qui les reinjecte lui-meme dans
 * les appels au backend. Une faille XSS ne peut donc plus les voler.
 *
 * Il ne reste ici qu'un INDICATEUR non sensible (« une session semble ouverte ») : il evite, pour un visiteur
 * anonyme, des appels /me et /refresh voues a l'echec. Il ne prouve rien et ne donne aucun acces : le
 * backend reste seul juge de la validite de la session.
 */
const INDICATEUR_SESSION_KEY = "workflows.session";

export function sessionProbable(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(INDICATEUR_SESSION_KEY) === "1";
}

function marquerSession() {
  if (typeof window !== "undefined") localStorage.setItem(INDICATEUR_SESSION_KEY, "1");
}

export function effacerSession() {
  if (typeof window !== "undefined") localStorage.removeItem(INDICATEUR_SESSION_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Emis quand la session ne peut plus etre renouvelee : AuthProvider y reagit (retour a /login). */
export const EVENEMENT_SESSION_EXPIREE = "workflows:session-expiree";

/**
 * Ecart trouve en verifiant la communication frontend/backend (27/09) :
 * POST /api/v1/auth/refresh existait cote backend mais n'etait JAMAIS
 * appele - le jeton de rafraichissement (14 jours) etait stocke sans
 * servir, et le jeton d'acces (45 min) expirait en silence : chaque appel
 * echouait en 401 sans que l'utilisateur soit renvoye vers la connexion.
 *
 * Une seule tentative de renouvellement a la fois, partagee entre tous les
 * appels concurrents (le backend renvoie un NOUVEAU jeton de rafraichissement
 * a chaque appel : plusieurs renouvellements paralleles s'invalideraient).
 */
let rafraichissementEnCours: Promise<boolean> | null = null;

function rafraichirSession(): Promise<boolean> {
  if (rafraichissementEnCours) return rafraichissementEnCours;
  rafraichissementEnCours = (async () => {
    try {
      // Aucun corps : le proxy lit le jeton de rafraichissement dans son cookie httpOnly.
      const reponse = await fetch(`${BASE_URL}/api/v1/auth/refresh`, { method: "POST" });
      return reponse.ok;
    } catch {
      return false;
    }
  })().finally(() => {
    rafraichissementEnCours = null;
  });
  return rafraichissementEnCours;
}

/**
 * fetch avec jeton d'acces ; sur 401, renouvelle la session puis rejoue UNE
 * fois la requete (les corps JSON et FormData sont rejouables). Si le
 * renouvellement echoue, la session est effacee et l'evenement
 * EVENEMENT_SESSION_EXPIREE est emis.
 */
async function fetchAuthentifie(
  chemin: string,
  init: { method?: string; headers?: Record<string, string>; body?: BodyInit },
  avecAuth = true
): Promise<Response> {
  // Le cookie de session part tout seul (meme origine) ; aucun en-tete Authorization n'est pose ici.
  const envoyer = () => fetch(`${BASE_URL}${chemin}`, { ...init, headers: { ...(init.headers ?? {}) } });

  let reponse = await envoyer();
  if (reponse.status === 401 && avecAuth && sessionProbable()) {
    if (await rafraichirSession()) {
      reponse = await envoyer();
    } else {
      effacerSession();
      if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENEMENT_SESSION_EXPIREE));
    }
  }
  return reponse;
}

async function erreurDepuis(reponse: Response): Promise<ApiError> {
  let message = `Erreur ${reponse.status}`;
  try {
    const corpsErreur = await reponse.json();
    if (corpsErreur?.detail) {
      message = typeof corpsErreur.detail === "string" ? corpsErreur.detail : JSON.stringify(corpsErreur.detail);
    }
  } catch {
    // corps de reponse non-JSON : on garde le message generique
  }
  return new ApiError(reponse.status, message);
}

async function requete<T>(
  chemin: string,
  options: { method?: string; corps?: unknown; avecAuth?: boolean } = {}
): Promise<T> {
  const { method = "GET", corps, avecAuth = true } = options;

  const reponse = await fetchAuthentifie(
    chemin,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: corps !== undefined ? JSON.stringify(corps) : undefined,
    },
    avecAuth
  );

  if (!reponse.ok) throw await erreurDepuis(reponse);

  if (reponse.status === 204) return undefined as T;
  return (await reponse.json()) as T;
}

// --- Authentification --------------------------------------------------

export async function login(email: string, mot_de_passe: string) {
  const session = await requete<SessionResponse>("/api/v1/auth/login", {
    method: "POST",
    corps: { email, mot_de_passe },
    avecAuth: false,
  });
  marquerSession();
  return session;
}

/** Ferme la session : le proxy efface les cookies httpOnly (le navigateur ne peut pas le faire lui-meme). */
export async function deconnecter() {
  try {
    await requete<SessionResponse>("/api/v1/auth/deconnexion", { method: "POST", avecAuth: false });
  } finally {
    effacerSession();
  }
}

export function quiSuisJe() {
  return requete<UtilisateurRead>("/api/v1/auth/me");
}

export function demanderReinitialisation(email: string) {
  return requete<{ detail: string }>("/api/v1/auth/mot-de-passe-oublie", {
    method: "POST",
    corps: { email },
    avecAuth: false,
  });
}

export async function definirMotDePasse(jeton: string, mot_de_passe: string) {
  const session = await requete<SessionResponse>("/api/v1/auth/definir-mot-de-passe", {
    method: "POST",
    corps: { jeton, mot_de_passe },
    avecAuth: false,
  });
  marquerSession();
  return session;
}

// --- Types de conge & jours feries (administration) ---------------------

export function listerTypesConge(inclureInactifs = false) {
  return requete<TypeConge[]>(`/api/v1/types-conge/${inclureInactifs ? "?inclure_inactifs=true" : ""}`, {
    avecAuth: false,
  });
}

export function creerTypeConge(payload: { code: string; nom: string; taux_acquisition_jours_mois: number }) {
  return requete<TypeConge>("/api/v1/types-conge/", { method: "POST", corps: payload });
}

export function desactiverTypeConge(id: string) {
  return requete<TypeConge>(`/api/v1/types-conge/${id}/desactiver`, { method: "POST" });
}

export function reactiverTypeConge(id: string) {
  return requete<TypeConge>(`/api/v1/types-conge/${id}/reactiver`, { method: "POST" });
}

export function listerSoldesConges(utilisateurId: string) {
  return requete<SoldeCongesRead[]>(`/api/v1/utilisateurs/${utilisateurId}/soldes-conges`);
}

export function definirSoldeConges(
  utilisateurId: string,
  payload: { type_conge_id: string; exercice: number; jours_acquis: number }
) {
  return requete<SoldeCongesRead>(`/api/v1/utilisateurs/${utilisateurId}/soldes-conges`, {
    method: "PUT",
    corps: payload,
  });
}

export function listerJoursFeries() {
  return requete<JourFerie[]>("/api/v1/jours-feries/", { avecAuth: false });
}

export function creerJourFerie(payload: { nom: string; date: string; recurrent: boolean }) {
  return requete<JourFerie>("/api/v1/jours-feries/", { method: "POST", corps: payload });
}

// --- Conges --------------------------------------------------------------

export function soumettreDemandeConges(payload: {
  type_conge_id: string;
  date_debut: string;
  date_fin: string;
  commentaire?: string;
}) {
  return requete<SoumissionCongesResponse>("/api/v1/conges/", { method: "POST", corps: payload });
}

export function listerMesDemandesConges() {
  return requete<DemandeConges[]>("/api/v1/conges/");
}

export function consulterDemandeConges(id: string) {
  return requete<DemandeConges>(`/api/v1/conges/${id}`);
}

export function modifierDemandeConges(
  id: string,
  payload: Partial<{ type_conge_id: string; date_debut: string; date_fin: string; commentaire: string }>
) {
  return requete(`/api/v1/conges/${id}`, { method: "PATCH", corps: payload });
}

export function annulerDemandeConges(id: string) {
  return requete<{ id: string; statut_global: string }>(`/api/v1/conges/${id}/annuler`, { method: "POST" });
}

export function relancerNotificationConges(id: string) {
  return requete<{ id: string; email_envoye: boolean; detail: string }>(`/api/v1/conges/${id}/relancer`, {
    method: "POST",
  });
}

// --- Annulation et relance manuelle, parité avec les congés (28/09) ---------------------------

export function annulerNoteDeFrais(id: string) {
  return requete<{ id: string; statut_global: string }>(`/api/v1/notes-frais/${id}/annuler`, { method: "POST" });
}

export function relancerNoteDeFrais(id: string) {
  return requete<{ id: string; email_envoye: boolean; detail: string }>(`/api/v1/notes-frais/${id}/relancer`, {
    method: "POST",
  });
}

export function annulerDemandeAchat(id: string) {
  return requete<{ id: string; statut_global: string }>(`/api/v1/achats/${id}/annuler`, { method: "POST" });
}

export function relancerDemandeAchat(id: string) {
  return requete<{ id: string; email_envoye: boolean; detail: string }>(`/api/v1/achats/${id}/relancer`, {
    method: "POST",
  });
}

export function regulariserDemandeConges(payload: {
  employe_id: string;
  type_conge_id: string;
  date_debut: string;
  date_fin: string;
  action: "approuver" | "refuser";
  commentaire?: string;
}) {
  return requete<RegularisationResponse>("/api/v1/conges/regularisation", { method: "POST", corps: payload });
}

export async function telechargerFicheConfirmation(id: string): Promise<Blob> {
  const reponse = await fetchAuthentifie(`/api/v1/conges/${id}/fiche-confirmation`, {});
  if (!reponse.ok) throw await erreurDepuis(reponse);
  return reponse.blob();
}

export function listerAgendaEquipe() {
  return requete<AgendaEquipeEvenement[]>("/api/v1/conges/agenda-equipe");
}

// --- Utilisateurs ----------------------------------------------------------

export function listerMonEquipe() {
  return requete<UtilisateurRead[]>("/api/v1/utilisateurs/mon-equipe");
}

export function listerTousLesComptes() {
  return requete<UtilisateurRead[]>("/api/v1/utilisateurs/");
}

export function creerCompte(payload: {
  email: string;
  nom_complet: string;
  service: string;
  role: RoleUtilisateur;
  manager_id?: string | null;
}) {
  return requete<UtilisateurRead>("/api/v1/utilisateurs/", { method: "POST", corps: payload });
}

export function modifierCompte(
  id: string,
  payload: Partial<{
    nom_complet: string;
    service: string;
    role: RoleUtilisateur;
    manager_id: string | null;
    actif: boolean;
  }>
) {
  return requete<UtilisateurModifie>(`/api/v1/utilisateurs/${id}`, { method: "PATCH", corps: payload });
}

export function desactiverCompte(id: string) {
  return requete<UtilisateurRead>(`/api/v1/utilisateurs/${id}/desactiver`, { method: "POST" });
}

export function reactiverCompte(id: string) {
  return requete<UtilisateurRead>(`/api/v1/utilisateurs/${id}/reactiver`, { method: "POST" });
}

export function renvoyerInvitation(id: string) {
  return requete<{ email_envoye: boolean; lien_activation: string; detail: string }>(
    `/api/v1/utilisateurs/${id}/renvoyer-invitation`,
    { method: "POST" }
  );
}

// --- Decision par lien e-mail (jeton) -------------------------------------

export function apercuDecision(jeton: string) {
  return requete<ApercuDecision>(`/api/v1/decisions/${jeton}`, { avecAuth: false });
}

export function decider(
  jeton: string,
  options: {
    commentaire?: string;
    signature_image_base64?: string;
    justification_acceptation?: string;
  } = {}
) {
  return requete<DecisionResponse>(`/api/v1/decisions/${jeton}`, {
    method: "POST",
    corps: options,
  });
}

// --- Notes de frais ------------------------------------------------------

export function soumettreNoteDeFrais(payload: NoteFraisCreate) {
  return requete<SoumissionNotesFraisResponse>("/api/v1/notes-frais/", {
    method: "POST",
    corps: payload,
  });
}

export function listerMesNotesDeFrais() {
  return requete<NoteFrais[]>("/api/v1/notes-frais/");
}


// --- Enveloppes budgetaires (DRH / controleur de gestion) ------------------

export function listerEnveloppesBudgetaires() {
  return requete<EnveloppeBudgetaire[]>("/api/v1/enveloppes-budgetaires/");
}

export function definirEnveloppeBudgetaire(payload: {
  service: string;
  exercice: number;
  budget_alloue: number;
}) {
  return requete<EnveloppeBudgetaire>("/api/v1/enveloppes-budgetaires/", {
    method: "PUT",
    corps: payload,
  });
}


// --- Achats (soumission multipart : le contrat est un vrai fichier) ---------

/**
 * POST /api/v1/achats/ attend du multipart/form-data (champ `fichier_contrat`),
 * pas du JSON - d'ou un fetch dedie plutot que `requete`. Le Content-Type
 * n'est volontairement PAS fixe ici : le navigateur y ajoute lui-meme la
 * frontiere (boundary) du multipart, sans quoi le corps serait illisible.
 */
/** Ligne detaillee d'un achat (app/schemas/achats.py:LigneAchat) : le montant est saisi HT, le TTC est calcule par le backend. */
export async function soumettreDemandeAchat(payload: {
  tiers: string;
  objet: string;
  budget_engage?: number;
  lignes?: LigneAchat[];
  devise?: string;
  derogation_motivee: boolean;
  motif_derogation?: string;
  fichier_contrat: File;
}): Promise<SoumissionAchatResponse> {
  const formulaire = new FormData();
  formulaire.append("tiers", payload.tiers);
  formulaire.append("objet", payload.objet);
  if (payload.lignes && payload.lignes.length > 0) {
    formulaire.append("lignes", JSON.stringify(payload.lignes));
  } else if (payload.budget_engage !== undefined) {
    formulaire.append("budget_engage", String(payload.budget_engage));
  }
  if (payload.devise) formulaire.append("devise", payload.devise);
  formulaire.append("derogation_motivee", payload.derogation_motivee ? "true" : "false");
  if (payload.derogation_motivee && payload.motif_derogation) {
    formulaire.append("motif_derogation", payload.motif_derogation);
  }
  formulaire.append("fichier_contrat", payload.fichier_contrat);

  const reponse = await fetchAuthentifie("/api/v1/achats/", { method: "POST", body: formulaire });
  if (!reponse.ok) throw await erreurDepuis(reponse);
  return (await reponse.json()) as SoumissionAchatResponse;
}

export function listerMesDemandesAchat() {
  return requete<DemandeAchat[]>("/api/v1/achats/");
}

async function telechargerBlob(chemin: string): Promise<Blob> {
  const reponse = await fetchAuthentifie(chemin, {});
  if (!reponse.ok) throw await erreurDepuis(reponse);
  return reponse.blob();
}

export function telechargerContratAchat(id: string) {
  return telechargerBlob(`/api/v1/achats/${id}/piece-jointe`);
}

export function telechargerBonDeCommande(id: string) {
  return telechargerBlob(`/api/v1/achats/${id}/bon-de-commande`);
}


// --- Discussion parallele au circuit (ecart n°5, section 4.5 du CDC) -----------

export function suspendreDemande(demandeId: string, message: string) {
  return requete<MessageClarification>(`/api/v1/demandes/${demandeId}/suspendre`, {
    method: "POST",
    corps: { message },
  });
}

export function listerMessages(demandeId: string) {
  return requete<MessageClarification[]>(`/api/v1/demandes/${demandeId}/messages`);
}

export function envoyerMessage(demandeId: string, contenu: string) {
  return requete<MessageClarification>(`/api/v1/demandes/${demandeId}/messages`, {
    method: "POST",
    corps: { contenu },
  });
}

export function reprendreDemande(demandeId: string) {
  return requete<{ id: string; statut_global: string }>(`/api/v1/demandes/${demandeId}/reprendre`, {
    method: "POST",
  });
}

/**
 * Depot d'une piece complementaire dans la discussion (CDC section 4.5) :
 * multipart, comme le contrat des achats - pas de Content-Type fixe.
 */
export async function envoyerMessageAvecFichier(demandeId: string, contenu: string, fichier: File) {
  const formulaire = new FormData();
  formulaire.append("contenu", contenu);
  formulaire.append("fichier", fichier);
  const reponse = await fetchAuthentifie(`/api/v1/demandes/${demandeId}/messages/avec-fichier`, {
    method: "POST",
    body: formulaire,
  });
  if (!reponse.ok) throw await erreurDepuis(reponse);
  return (await reponse.json()) as MessageClarification;
}

export function telechargerFichierMessage(demandeId: string, messageId: string) {
  return telechargerBlob(`/api/v1/demandes/${demandeId}/messages/${messageId}/fichier`);
}

// --- Pieces jointes d'une demande (recu, justificatif d'absence, complements) ---------

/** Depot facultatif d'une piece sur SA demande ; la categorie est deduite du processus par le backend. */
export async function deposerPieceJointe(demandeId: string, fichier: File) {
  const formulaire = new FormData();
  formulaire.append("fichier", fichier);
  const reponse = await fetchAuthentifie(`/api/v1/demandes/${demandeId}/pieces-jointes`, {
    method: "POST",
    body: formulaire,
  });
  if (!reponse.ok) throw await erreurDepuis(reponse);
  return (await reponse.json()) as PieceJointe;
}

export function telechargerPieceJointe(demandeId: string, pieceId: string) {
  return telechargerBlob(`/api/v1/demandes/${demandeId}/pieces-jointes/${pieceId}`);
}

// --- Journal d'audit (CDC 2.4) ----------------------------------------------------------

export interface FiltresAudit {
  action?: string;
  depuis?: string;
  jusqu_a?: string;
  limit?: number;
  offset?: number;
}

/** Journal filtre, du plus recent au plus ancien - reserve a la DRH, la Direction generale et le Controleur de gestion. */
export function consulterJournal(filtres: FiltresAudit = {}) {
  const requete_ = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(filtres)) {
    if (valeur !== undefined && valeur !== "") requete_.set(cle, String(valeur));
  }
  const suffixe = requete_.toString();
  return requete<AuditPage>(`/api/v1/audit/${suffixe ? `?${suffixe}` : ""}`);
}

export function listerActionsAudit() {
  return requete<ActionAudit[]>("/api/v1/audit/actions");
}

/** Chronologie d'un dossier pour ses participants. */
export function historiqueDemande(demandeId: string) {
  return requete<HistoriqueEntree[]>(`/api/v1/demandes/${demandeId}/historique`);
}

// --- Devises et taux de change (plusieurs devises avec conversion) -----------------------------

export function listerDevises() {
  return requete<DevisesReponse>("/api/v1/devises/");
}

/** Apercu de conversion pour les formulaires : au taux qui serait applique a cette date. */
export function convertirMontant(params: { montant: number; devise: string; date?: string }) {
  const q = new URLSearchParams({ montant: String(params.montant), devise: params.devise });
  if (params.date) q.set("date", params.date);
  return requete<Conversion>(`/api/v1/devises/convertir?${q.toString()}`);
}

export function listerTauxChange() {
  return requete<TauxChange[]>("/api/v1/taux-change/");
}

export function definirTauxChange(payload: { devise: string; taux: number; date_effet: string }) {
  return requete<TauxChange>("/api/v1/taux-change/", { method: "PUT", corps: payload });
}

// --- Synthese des notes de frais validees (comptabilite) -------------------------------------

export interface FiltresSynthese {
  depuis?: string;
  jusqu_a?: string;
  service?: string;
  limit?: number;
  offset?: number;
}

function chaineRequete<T extends Record<string, string | number | undefined>>(filtres: T): string {
  const q = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(filtres)) {
    if (valeur !== undefined && valeur !== "") q.set(cle, String(valeur));
  }
  return q.toString();
}

export function syntheseNotesDeFrais(filtres: FiltresSynthese = {}) {
  const suffixe = chaineRequete({ ...filtres });
  return requete<SyntheseFrais>(`/api/v1/notes-frais/synthese${suffixe ? `?${suffixe}` : ""}`);
}

/** Export CSV de toute la selection (pas seulement la page affichee). */
export function exporterSyntheseCsv(filtres: Omit<FiltresSynthese, "limit" | "offset"> = {}) {
  const suffixe = chaineRequete({ ...filtres });
  return telechargerBlob(`/api/v1/notes-frais/synthese.csv${suffixe ? `?${suffixe}` : ""}`);
}

export function listerPiecesJointes(demandeId: string) {
  return requete<PieceJointe[]>(`/api/v1/demandes/${demandeId}/pieces-jointes`);
}
