// Types alignés sur les schémas Pydantic du backend (app/schemas/*.py).

export type RoleUtilisateur =
  | "employe"
  | "manager"
  | "drh"
  | "direction_financiere"
  | "service_juridique"
  | "direction_generale"
  | "controleur_de_gestion";

export type StatutDemande = "en_cours" | "terminee" | "refusee" | "complement_demande" | "annulee";

/**
 * Reponse du proxy a la connexion, a l'activation et au renouvellement (R23). Elle ne contient AUCUN jeton :
 * ils sont dans des cookies httpOnly, hors de portee du JavaScript.
 */
export interface SessionResponse {
  connecte: boolean;
}

export interface TypeConge {
  id: string;
  code: string;
  nom: string;
  taux_acquisition_jours_mois: number;
  actif: boolean;
}

export interface SoldeCongesRead {
  id: string;
  type_conge_id: string;
  exercice: number;
  jours_acquis: number;
  jours_pris: number;
  solde_jours: number;
}

export interface JourFerie {
  id: string;
  nom: string;
  date: string; // ISO yyyy-mm-dd
  recurrent: boolean;
}

export interface DemandeCongesDonnees {
  type_conge_id: string;
  date_debut: string;
  date_fin: string;
  commentaire?: string | null;
}

export interface DemandeConges {
  id: string;
  statut_global: StatutDemande;
  donnees: DemandeCongesDonnees;
  creee_le?: string;
  pieces_jointes?: PieceJointe[];
}

export interface SoumissionCongesResponse {
  id: string;
  statut_global: StatutDemande;
  nombre_jours: number;
  premiere_etape_id: string;
}

/**
 * Reponse reelle de POST /api/v1/conges/regularisation (verifie dans
 * app/routers/conges.py) : contrairement a SoumissionCongesResponse,
 * aucune etape de workflow separee n'est creee (la decision est immediate),
 * donc pas de premiere_etape_id.
 */
export interface RegularisationResponse {
  id: string;
  statut_global: StatutDemande;
  nombre_jours: number;
}

export interface DecisionResponse {
  demande_id: string;
  etape_id: string;
  action: "approuver" | "refuser" | "signer";
  statut_global: StatutDemande;
}

/** GET /api/v1/decisions/{jeton} (app/schemas/decisions.py:ApercuDecision) - lecture seule, ne consomme jamais le jeton. */
export interface ApercuDecision {
  action: "approuver" | "refuser" | "signer";
  processus: "conges" | "notes_frais" | "achats";
  est_derogation: boolean;
  demande_id: string;
  statut_demande: StatutDemande;
  demandeur_nom: string;
  resume: Record<string, unknown>;
  pieces_jointes: PieceJointe[];
  /** Situation budgetaire du service du demandeur (notes de frais, achats) ; null pour les conges. */
  budget: BudgetApercu | null;
}

export interface BudgetApercu {
  service: string;
  exercice: number;
  solde_disponible: number;
  montant_demande: number;
  solde_apres_validation: number;
  /** Devise de reference, celle des enveloppes. */
  devise: string;
}

/** Corps de POST /api/v1/notes-frais/ (app/schemas/notes_frais.py:NoteFraisCreate). */
export interface NoteFraisCreate {
  montant: number;
  categorie: string;
  date_depense: string;
  description: string;
  /** Code ISO 4217 ; absent : devise de reference. Converti a la soumission. */
  devise?: string;
  derogation_motivee: boolean;
  motif_derogation?: string;
}

/** Reponse de POST /api/v1/notes-frais/ (SoumissionNotesFraisResponse). */
export interface SoumissionNotesFraisResponse {
  id: string;
  statut_global: StatutDemande;
  premiere_etape_id: string;
  derogation: boolean;
  /** Conversion figee a la soumission. */
  devise: string;
  taux_applique: number;
  montant_reference: number;
}

/** Element de GET /api/v1/notes-frais/ (NoteFraisRead). */
export interface NoteFrais {
  id: string;
  statut_global: StatutDemande;
  donnees: {
    montant: number;
    categorie: string;
    date_depense: string;
    description: string;
    devise?: string;
    taux_applique?: number;
    montant_reference?: number;
    derogation_motivee?: boolean;
    motif_derogation?: string | null;
  };
  creee_le?: string;
  pieces_jointes?: PieceJointe[];
}

/** Réponse de GET /api/v1/auth/me (app/schemas/user.py). */
export interface UtilisateurRead {
  id: string;
  email: string;
  nom_complet: string;
  service: string;
  role: RoleUtilisateur;
  manager_id: string | null;
  actif: boolean;
  compte_active: boolean;
}

/** Reponse de PATCH /api/v1/utilisateurs/{id} : le profil + les demandes en cours transmises a un nouveau manager. */
export interface UtilisateurModifie extends UtilisateurRead {
  demandes_reaffectees: number;
}

/** Un événement de GET /api/v1/conges/agenda-equipe (absence approuvée). */
export interface AgendaEquipeEvenement {
  demande_id: string;
  employe_id: string;
  employe_nom: string;
  date_debut: string;
  date_fin: string;
}

/** GET/PUT /api/v1/enveloppes-budgetaires/ (app/schemas/budget.py). */
export interface EnveloppeBudgetaire {
  id: string;
  service: string;
  exercice: number;
  budget_alloue: number;
  budget_consomme: number;
  solde_disponible: number;
}

/** Reponse de POST /api/v1/achats/ (SoumissionAchatResponse). */
export interface SoumissionAchatResponse {
  id: string;
  statut_global: StatutDemande;
  premiere_etape_id: string;
  derogation: boolean;
  devise: string;
  taux_applique: number;
  budget_engage_reference: number;
}

/** Element de GET /api/v1/achats/ (DemandeAchatRead). */
/** Ligne detaillee d'un achat (app/schemas/achats.py:LigneAchat) : le montant est saisi HT, le TTC est calcule par le backend. */
export interface LigneAchat {
  description: string;
  montant_ht: number;
  taux_tva: number;
}

export interface DemandeAchat {
  id: string;
  statut_global: StatutDemande;
  donnees: {
    tiers: string;
    objet: string;
    budget_engage: number;
    devise?: string;
    taux_applique?: number;
    budget_engage_reference?: number;
    lignes?: LigneAchat[] | null;
    derogation_motivee?: boolean;
    motif_derogation?: string | null;
    numero_bc?: string;
  };
  creee_le?: string;
  pieces_jointes?: PieceJointe[];
}

/** Message de discussion (app/schemas/clarifications.py:MessageRead). */
export interface MessageClarification {
  id: string;
  auteur_id: string;
  auteur_nom: string;
  contenu: string;
  cree_le: string;
  /** Nom de la piece complementaire deposee avec ce message, le cas echeant. */
  fichier_nom?: string | null;
}

/** Piece jointe d'un dossier (app/schemas/pieces_jointes.py) : recu, justificatif, contrat ou complement. */
export interface PieceJointe {
  id: string;
  nom: string;
  categorie: string;
}

/** Entree du journal d'audit (app/schemas/audit.py:AuditEntree) - consultation reservee aux roles de controle. */
export interface AuditEntree {
  id: string;
  action: string;
  libelle: string;
  acteur_id: string | null;
  acteur_nom: string;
  cible_type: string;
  cible_id: string | null;
  details: Record<string, unknown>;
  horodate_le: string;
}

export interface AuditPage {
  total: number;
  limit: number;
  offset: number;
  elements: AuditEntree[];
}

export interface ActionAudit {
  action: string;
  libelle: string;
}

/** Ligne de la chronologie d'un dossier (GET /api/v1/demandes/{id}/historique). */
export interface HistoriqueEntree {
  horodate_le: string;
  action: string;
  libelle: string;
  acteur_nom: string;
  detail: string | null;
}

/** Devise utilisable et son taux applicable aujourd'hui (GET /api/v1/devises/). */
export interface Devise {
  code: string;
  taux: number;
  date_effet: string | null;
}

export interface DevisesReponse {
  reference: string;
  devises: Devise[];
}

/** GET /api/v1/devises/convertir : equivalent en devise de reference, au taux applicable a la date. */
export interface Conversion {
  devise: string;
  devise_reference: string;
  taux: number;
  montant: number;
  montant_reference: number;
  date_effet: string | null;
}

export interface TauxChange {
  id: string;
  devise: string;
  taux: number;
  date_effet: string;
}

/** Ligne de la synthese des notes de frais validees (GET /api/v1/notes-frais/synthese). */
export interface LigneSynthese {
  id: string;
  valide_le: string;
  demandeur_nom: string;
  service: string;
  categorie: string;
  date_depense: string;
  description: string;
  montant: number;
  devise: string;
  taux_applique: number;
  montant_reference: number;
  valide_par: string[];
  derogation: boolean;
  nb_pieces: number;
}

export interface TotalDevise {
  devise: string;
  nombre: number;
  total: number;
  total_reference: number;
}

export interface SyntheseFrais {
  devise_reference: string;
  nombre: number;
  total_reference: number;
  par_devise: TotalDevise[];
  total_lignes: number;
  limit: number;
  offset: number;
  tronque: boolean;
  elements: LigneSynthese[];
}
