"use client";

import { ChampFichier } from "@/components/champ-fichier";
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TAILLE_MAX_FICHIER_MO, messageTailleFichier } from "@/lib/fichiers";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Textarea,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { ApercuConversion, ChampDevise, useDevises } from "@/components/champ-devise";
import { LignesAchat } from "@/components/lignes-achat";
import { ApiError, soumettreDemandeAchat } from "@/lib/api";
import type { LigneAchat } from "@/types";

export default function AchatsPage() {
  const router = useRouter();
  const minuterie = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  // Quitter la page avant la redirection annule celle-ci (jamais de navigation surprise ailleurs).
  React.useEffect(() => () => { if (minuterie.current) clearTimeout(minuterie.current); }, []);
  const [tiers, setTiers] = React.useState("");
  const [objet, setObjet] = React.useState("");
  const [budget, setBudget] = React.useState("");
  const [modeDetail, setModeDetail] = React.useState(false);
  const [lignes, setLignes] = React.useState<LigneAchat[]>([{ description: "", montant_ht: 0, taux_tva: 20 }]);
  const [devise, setDevise] = React.useState("");
  const { reference, devises } = useDevises();
  const [fichier, setFichier] = React.useState<File | null>(null);
  const [derogation, setDerogation] = React.useState(false);
  const [motif, setMotif] = React.useState("");
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [succes, setSucces] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErreur(null);
    setSucces(null);

    const tropGros = messageTailleFichier(fichier);
    if (tropGros) {
      setErreur(tropGros);
      return;
    }

    let lignesValides: LigneAchat[] | undefined;
    let valeurBudget: number | undefined;
    if (modeDetail) {
      lignesValides = lignes.filter((l) => l.description.trim() && l.montant_ht > 0);
      if (lignesValides.length === 0) {
        setErreur("Indiquez au moins une ligne avec une description et un montant HT positif.");
        return;
      }
    } else {
      valeurBudget = parseFloat(budget);
      if (!Number.isFinite(valeurBudget) || valeurBudget <= 0) {
        setErreur("Le budget engagé doit être un nombre strictement positif.");
        return;
      }
    }
    if (!fichier) {
      setErreur("Le fichier du contrat est obligatoire.");
      return;
    }
    if (derogation && !motif.trim()) {
      setErreur("Un motif est obligatoire lorsque la dérogation est demandée.");
      return;
    }

    setEnCours(true);
    try {
      const resultat = await soumettreDemandeAchat({
        tiers: tiers.trim(),
        objet: objet.trim(),
        budget_engage: valeurBudget,
        lignes: lignesValides,
        devise: devise && devise !== reference ? devise : undefined,
        derogation_motivee: derogation,
        motif_derogation: derogation ? motif.trim() : undefined,
        fichier_contrat: fichier,
      });
      setSucces(
        resultat.derogation
          ? "Demande d'achat soumise pour arbitrage exceptionnel (dérogation)."
          : "Demande d'achat soumise. Le service juridique a été notifié."
      );
      setTiers("");
      setObjet("");
      setBudget("");
      setLignes([{ description: "", montant_ht: 0, taux_tva: 20 }]);
      setDevise("");
      setFichier(null);
      setDerogation(false);
      setMotif("");
      minuterie.current = setTimeout(() => router.push("/mes-demandes?type=achats"), 1200); // le suivi se fait dans « Mes demandes »
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Une erreur est survenue.";
      setErreur(message);
      if (message.toLowerCase().includes("motif de dérogation")) setDerogation(true);
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <h1 className="titre-page text-center">Validation d&apos;achats et contrats</h1>

      <Card className="mx-auto w-full max-w-3xl">
        <CardHeader>
          <CardTitle>Nouvelle demande d&apos;achat</CardTitle>
          <CardDescription>
            Avis du service juridique, puis signature de la Direction générale. Le contrat est obligatoire
            (PDF, Word, PNG ou JPEG, {TAILLE_MAX_FICHIER_MO} Mo maximum).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={onSubmit}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ach-tiers">Fournisseur / tiers</Label>
                <Input id="ach-tiers" value={tiers} onChange={(e) => setTiers(e.target.value)} required />
              </div>
              {!modeDetail && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="ach-budget">Budget engagé TTC ({devise || reference})</Label>
                  <div className="flex gap-2">
                    <Input
                      id="ach-budget"
                      className="min-w-0 flex-1"
                      type="number"
                      step="0.01"
                      min="0"
                      value={budget}
                      onChange={(e) => setBudget(e.target.value)}
                      required
                    />
                    <ChampDevise id="ach-devise" valeur={devise || reference} onChange={setDevise} devises={devises} />
                  </div>
                  <ApercuConversion montant={budget} devise={devise} reference={reference} />
                </div>
              )}
              {modeDetail && devises.length > 1 && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="ach-devise-detail">Devise</Label>
                  <ChampDevise id="ach-devise-detail" valeur={devise || reference} onChange={setDevise} devises={devises} />
                </div>
              )}
            </div>

            <div className="flex items-center justify-between">
              <Label>Montant de la commande</Label>
              <button
                type="button"
                onClick={() => setModeDetail((v) => !v)}
                className="text-[12.5px] text-accent-text hover:underline"
              >
                {modeDetail ? "Revenir à un montant global" : "Détailler par ligne (TVA différenciée)"}
              </button>
            </div>
            {modeDetail && <LignesAchat lignes={lignes} onChange={setLignes} devise={devise || reference} />}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ach-objet">Objet de la dépense</Label>
              <Textarea id="ach-objet" value={objet} onChange={(e) => setObjet(e.target.value)} maxLength={500} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ach-contrat">Fichier du contrat</Label>
              <ChampFichier
                id="ach-contrat"
               
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                onChange={(e) => setFichier(e.target.files?.[0] ?? null)}
              />
            </div>

            <label className="flex items-center gap-2 text-[13.5px] text-ink">
              <input
                type="checkbox"
                checked={derogation}
                onChange={(e) => setDerogation(e.target.checked)}
                className="h-4 w-4 accent-[var(--accent)]"
              />
              Demande de dérogation motivée (arbitrage exceptionnel)
            </label>
            {derogation && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ach-motif">Motif de la dérogation</Label>
                <Textarea id="ach-motif" value={motif} onChange={(e) => setMotif(e.target.value)} maxLength={1000} />
              </div>
            )}

            {erreur && <Alert variant="destructive">{erreur}</Alert>}
            {succes && <Alert variant="success">{succes}</Alert>}
            {succes && (
              <Link href="/mes-demandes?type=achats" className="text-center text-[13px] font-medium text-accent-text hover:underline">
                Suivre ma demande dans « Mes demandes »
              </Link>
            )}

            <Button type="submit" className="h-10 w-full" disabled={enCours}>
              {enCours ? "Envoi…" : "Soumettre la demande d'achat"}
            </Button>
          </form>
        </CardContent>
      </Card>

    </div>
  );
}
