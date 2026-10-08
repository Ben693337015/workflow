"use client";

import { Marque } from "@/components/marque";
import * as React from "react";
import { useParams } from "next/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Label,
  Textarea,
  Alert,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { DiscussionPanel } from "@/components/discussion-panel";
import { HistoriqueDossier } from "@/components/historique-dossier";
import { PiecesJointes } from "@/components/pieces-jointes";
import { SignaturePad } from "@/components/signature-pad";
import { useAuth } from "@/hooks/useAuth";
import { formaterAvecEquivalent, formaterMontant } from "@/lib/montants";
import { ApiError, apercuDecision, decider, suspendreDemande } from "@/lib/api";
import type { ApercuDecision } from "@/types";
import LoginPage from "@/app/login/page";

const TITRES: Record<ApercuDecision["processus"], string> = {
  conges: "demande de congés",
  notes_frais: "note de frais",
  achats: "demande d'achat",
};

/** Statuts pour lesquels le lien de decision n'a plus d'objet (la demande n'attend plus personne). */
const MESSAGES_STATUT_CLOS: Record<string, string> = {
  terminee: "Cette demande a déjà été traitée.",
  refusee: "Cette demande a déjà été refusée.",
  annulee: "Cette demande a été annulée par le demandeur : aucune décision n'est plus nécessaire.",
};

/** Montant dans SA devise d'origine, avec l'équivalent en devise de référence si elles diffèrent (jamais « € » en dur). */
function montantAffiche(
  r: Record<string, string | number | undefined>,
  cle: string,
  cleReference: string,
  reference: string
): string {
  const devise = typeof r.devise === "string" && r.devise ? r.devise : reference;
  const ref = r[cleReference];
  return formaterAvecEquivalent(Number(r[cle]), devise, typeof ref === "number" ? ref : undefined, reference);
}

function resumeLignes(apercu: ApercuDecision): string[] {
  const r = apercu.resume as Record<string, string | number | undefined>;
  const reference = apercu.budget?.devise ?? "EUR";
  const lignes: string[] = [];
  if (apercu.processus === "conges") {
    lignes.push(`Du ${r.date_debut} au ${r.date_fin}`);
  } else if (apercu.processus === "notes_frais") {
    lignes.push(`${montantAffiche(r, "montant", "montant_reference", reference)} — ${r.categorie} (${r.date_depense})`);
    if (r.description) lignes.push(String(r.description));
  } else {
    lignes.push(`${r.tiers} — ${montantAffiche(r, "budget_engage", "budget_engage_reference", reference)}`);
    if (r.objet) lignes.push(String(r.objet));
  }
  if (r.motif_derogation) lignes.push(`Motif de dérogation : ${r.motif_derogation}`);
  return lignes;
}

/**
 * Solde budgetaire montre au decideur (CDC 4.3 : "obligatoirement affiche de
 * maniere visuelle") - vert si l'enveloppe suffit, rouge en cas de
 * depassement. Le budget n'est consomme qu'a la fin du circuit : le solde
 * affiche est celui d'avant cette demande.
 */
function BlocBudget({ budget }: { budget: NonNullable<ApercuDecision["budget"]> }) {
  const depassement = budget.solde_apres_validation < 0;
  return (
    <div
      role="group"
      aria-label="Budget du service"
      className={`rounded-lg border border-current/30 p-3 text-[13px] ${
        depassement ? "bg-danger-soft text-danger" : "bg-accent-soft text-accent-ink"
      }`}
    >
      <p className="font-semibold">
        Budget du service « {budget.service} » ({budget.exercice}) —{" "}
        {depassement ? "Dépassement de l'enveloppe" : "Enveloppe suffisante"}
      </p>
      <p>
        Solde disponible : {formaterMontant(budget.solde_disponible, budget.devise)} · Montant demandé :{" "}
        {formaterMontant(budget.montant_demande, budget.devise)} · Solde après validation :{" "}
        {formaterMontant(budget.solde_apres_validation, budget.devise)}
      </p>
    </div>
  );
}

/**
 * Page de decision publique (section 3.1 / 9.1 du CDC technique), generique
 * aux trois processus. L'action reelle (approuver / refuser / signer) est
 * portee par le JETON, pas par un bouton : chaque lien recu par e-mail
 * correspond a une seule action. Ecart corrige (revue du 27/09) : l'ancienne
 * version affichait deux boutons, Approuver et Refuser, alors que le jeton
 * decidait seul - cliquer "Refuser" sur un lien d'approbation approuvait la
 * demande. On lit desormais l'action via GET /api/v1/decisions/{jeton}
 * (lecture seule, ne consomme pas le jeton) et on n'affiche que le
 * formulaire correspondant : signature pour "signer", justification
 * d'acceptation pour une derogation approuvee, commentaire pour un refus.
 */
export default function DecisionPage() {
  const params = useParams<{ jeton: string }>();
  const jeton = params?.jeton;
  const { connecte, utilisateur, chargement: chargementSession } = useAuth();
  const [apercu, setApercu] = React.useState<ApercuDecision | null>(null);
  const [erreurApercu, setErreurApercu] = React.useState<string | null>(null);
  const [commentaire, setCommentaire] = React.useState("");
  const [justification, setJustification] = React.useState("");
  const [signature, setSignature] = React.useState<string | null>(null);
  const [resultat, setResultat] = React.useState<string | null>(null);
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);
  const [precisionsOuvertes, setPrecisionsOuvertes] = React.useState(false);
  const [messagePrecisions, setMessagePrecisions] = React.useState("");

  const chargerApercu = React.useCallback(() => {
    if (!jeton) return;
    apercuDecision(jeton)
      .then(setApercu)
      .catch((err) =>
        setErreurApercu(err instanceof ApiError ? err.message : "Lien de décision invalide ou expiré.")
      );
  }, [jeton]);

  React.useEffect(() => {
    chargerApercu();
  }, [chargerApercu]);

  // Ecart n°5 (section 4.5 du CDC) : suspendre le circuit pour demander des
  // precisions au demandeur plutot que de refuser en bloc - le meme lien de
  // decision reste valable, la page bascule sur la discussion tant que le
  // statut de la demande est "complement_demande", puis revient au
  // formulaire de decision apres la reprise.
  async function onSuspendre() {
    if (!apercu) return;
    if (!messagePrecisions.trim()) {
      setErreur("Décrivez les précisions attendues du demandeur.");
      return;
    }
    setErreur(null);
    setEnCours(true);
    try {
      await suspendreDemande(apercu.demande_id, messagePrecisions.trim());
      setMessagePrecisions("");
      setPrecisionsOuvertes(false);
      chargerApercu();
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Une erreur est survenue.");
    } finally {
      setEnCours(false);
    }
  }

  async function onConfirmer() {
    if (!jeton || !apercu) return;
    setErreur(null);

    if (apercu.action === "refuser" && !commentaire.trim()) {
      setErreur("Un commentaire est obligatoire en cas de refus.");
      return;
    }
    if (apercu.action === "signer" && !signature) {
      setErreur("Une signature est obligatoire pour valider cette étape.");
      return;
    }
    if (apercu.est_derogation && apercu.action !== "refuser" && !justification.trim()) {
      setErreur("Une justification d'acceptation est obligatoire pour valider une dérogation.");
      return;
    }

    setEnCours(true);
    try {
      await decider(jeton, {
        commentaire: commentaire.trim() || undefined,
        signature_image_base64: apercu.action === "signer" ? (signature ?? undefined) : undefined,
        justification_acceptation:
          apercu.est_derogation && apercu.action !== "refuser" ? justification.trim() : undefined,
      });
      setResultat(
        apercu.action === "refuser"
          ? "Demande refusée. Le demandeur a été notifié."
          : apercu.action === "signer"
            ? "Document signé. Le demandeur a été notifié."
            : "Demande approuvée. Le demandeur a été notifié."
      );
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Une erreur est survenue.");
    } finally {
      setEnCours(false);
    }
  }

  if (chargementSession) {
    return <p className="p-8 text-center text-[13.5px] text-ink-dim">Chargement…</p>;
  }

  if (!connecte) {
    return (
      <div className="flex flex-col items-center gap-4 bg-sidebar pt-12">
        <div className="w-full max-w-md px-4">
          <Alert>
            Vous devez vous connecter pour confirmer cette décision (vérification d&apos;identité
            de l&apos;approbateur).
          </Alert>
        </div>
        <LoginPage redirigerApresConnexion={false} />
      </div>
    );
  }

  const libelleBouton =
    apercu?.action === "refuser" ? "Confirmer le refus" : apercu?.action === "signer" ? "Signer" : "Confirmer l'approbation";

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-canvas px-4 py-8">
      <div className="flex items-center gap-2.5">
        <Marque />
        <p className="text-[15px] font-semibold text-ink">Plateforme Workflows</p>
      </div>
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>
            {apercu ? `Décision — ${TITRES[apercu.processus]}` : "Décision"}
          </CardTitle>
          {apercu && (
            <CardDescription>
              {apercu.est_derogation && "Arbitrage exceptionnel (dérogation). "}
              Demande de {apercu.demandeur_nom}.
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {erreurApercu ? (
            <Alert variant="destructive">{erreurApercu}</Alert>
          ) : !apercu ? (
            <p className="text-[13.5px] text-ink-dim">Chargement de la demande…</p>
          ) : resultat ? (
            <Alert variant="success">{resultat}</Alert>
          ) : MESSAGES_STATUT_CLOS[apercu.statut_demande] ? (
            <Alert>{MESSAGES_STATUT_CLOS[apercu.statut_demande]}</Alert>
          ) : apercu.statut_demande === "complement_demande" ? (
            <>
              <Alert>
                Cette demande est en attente de précisions : échangez avec le demandeur, puis reprenez le
                workflow pour décider.
              </Alert>
              <DiscussionPanel demandeId={apercu.demande_id} onReprise={chargerApercu} utilisateurId={utilisateur?.id} />
            </>
          ) : (
            <>
              <ul className="rounded-lg bg-canvas p-3 text-[13.5px] text-ink">
                {resumeLignes(apercu).map((ligne, i) => (
                  <li key={i}>{ligne}</li>
                ))}
              </ul>

              {apercu.budget && <BlocBudget budget={apercu.budget} />}

              {apercu.pieces_jointes?.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <Label>Pièces jointes</Label>
                  <PiecesJointes demandeId={apercu.demande_id} pieces={apercu.pieces_jointes} />
                </div>
              )}

              <HistoriqueDossier demandeId={apercu.demande_id} />

              {apercu.est_derogation && apercu.action !== "refuser" && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="justification">Justification d&apos;acceptation (obligatoire)</Label>
                  <Textarea
                    id="justification"
                    value={justification}
                    onChange={(e) => setJustification(e.target.value)}
                  />
                </div>
              )}

              {apercu.action === "signer" && (
                <div className="flex flex-col gap-1.5">
                  <Label>Signature (obligatoire)</Label>
                  <SignaturePad onChange={setSignature} />
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="commentaire">
                  Commentaire {apercu.action === "refuser" ? "(obligatoire)" : "(facultatif)"}
                </Label>
                <Textarea
                  id="commentaire"
                  value={commentaire}
                  onChange={(e) => setCommentaire(e.target.value)}
                  placeholder="Motif, précisions…"
                />
              </div>

              {erreur && <Alert variant="destructive">{erreur}</Alert>}

              <Button
                className="h-10 w-full"
                variant={apercu.action === "refuser" ? "destructive" : "default"}
                onClick={onConfirmer}
                disabled={enCours}
              >
                {enCours ? "…" : libelleBouton}
              </Button>

              {!precisionsOuvertes ? (
                <button
                  type="button"
                  onClick={() => setPrecisionsOuvertes(true)}
                  className="text-center text-[12.5px] text-ink-dim hover:text-accent"
                >
                  Un doute ? Demander des précisions au demandeur
                </button>
              ) : (
                <div className="flex flex-col gap-2 rounded-lg border border-line p-3">
                  <Label htmlFor="precisions">Précisions attendues</Label>
                  <Textarea
                    id="precisions"
                    value={messagePrecisions}
                    onChange={(e) => setMessagePrecisions(e.target.value)}
                    maxLength={2000}
                  />
                  <Button type="button" variant="outline" onClick={onSuspendre} disabled={enCours}>
                    Suspendre et demander des précisions
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
