"use client";

import { ChampFichier } from "@/components/champ-fichier";
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { messageTailleFichier } from "@/lib/fichiers";
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
import { ApiError, deposerPieceJointe, soumettreNoteDeFrais } from "@/lib/api";

export default function NotesFraisPage() {
  const router = useRouter();
  const minuterie = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  // Quitter la page avant la redirection annule celle-ci (jamais de navigation surprise ailleurs).
  React.useEffect(() => () => { if (minuterie.current) clearTimeout(minuterie.current); }, []);
  const [montant, setMontant] = React.useState("");
  const [devise, setDevise] = React.useState("");
  const { reference, devises } = useDevises();
  const [categorie, setCategorie] = React.useState("");
  const [dateDepense, setDateDepense] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [derogation, setDerogation] = React.useState(false);
  const [motif, setMotif] = React.useState("");
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [succes, setSucces] = React.useState<string | null>(null);
  const [avertissement, setAvertissement] = React.useState<string | null>(null);
  const [recu, setRecu] = React.useState<File | null>(null);
  const [cleRecu, setCleRecu] = React.useState(0);
  const [enCours, setEnCours] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErreur(null);
    setSucces(null);
    setAvertissement(null);

    // Avant la creation de la note : sinon la note existerait deja avec un recu refuse.
    const tropGros = messageTailleFichier(recu);
    if (tropGros) {
      setErreur(tropGros);
      return;
    }

    const valeur = parseFloat(montant);
    if (!Number.isFinite(valeur) || valeur <= 0) {
      setErreur("Le montant doit être un nombre strictement positif.");
      return;
    }
    if (derogation && !motif.trim()) {
      setErreur("Un motif est obligatoire lorsque la dérogation est demandée.");
      return;
    }

    setEnCours(true);
    try {
      const resultat = await soumettreNoteDeFrais({
        montant: valeur,
        categorie: categorie.trim(),
        date_depense: dateDepense,
        description: description.trim(),
        devise: devise && devise !== reference ? devise : undefined,
        derogation_motivee: derogation,
        motif_derogation: derogation ? motif.trim() : undefined,
      });
      setSucces(
        resultat.derogation
          ? "Note de frais soumise pour arbitrage exceptionnel (dérogation)."
          : "Note de frais soumise. Votre manager a été notifié."
      );
      // Le reçu est facultatif : la note existe d'abord, la piece s'y attache ensuite. Un echec
      // d'envoi ne remet donc jamais en cause la note deja soumise - on le signale seulement.
      let depotEchoue = false;
      if (recu) {
        try {
          await deposerPieceJointe(resultat.id, recu);
        } catch (err) {
          depotEchoue = true;
          setAvertissement(
            `Note soumise, mais le reçu n'a pas pu être envoyé (${err instanceof ApiError ? err.message : "erreur"}). ` +
              "Vous pouvez l'ajouter depuis « Mes demandes »."
          );
        }
      }
      setRecu(null);
      setCleRecu((n) => n + 1);
      setMontant("");
      setDevise("");
      setCategorie("");
      setDateDepense("");
      setDescription("");
      setDerogation(false);
      setMotif("");
      // Le suivi se fait dans « Mes demandes » : on y renvoie, sauf si un avertissement doit rester lisible.
      if (!depotEchoue) minuterie.current = setTimeout(() => router.push("/mes-demandes?type=notes_frais"), 1200);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Une erreur est survenue.";
      setErreur(message);
      // Budget insuffisant : le backend exige un motif de dérogation pour
      // soumettre malgré tout (CDC section 4.4) - on coche la case pour
      // guider l'utilisateur plutôt que de le laisser deviner.
      if (message.toLowerCase().includes("motif de dérogation")) setDerogation(true);
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <h1 className="titre-page text-center">Notes de frais</h1>

      <Card className="mx-auto w-full max-w-3xl">
        <CardHeader>
          <CardTitle>Nouvelle note de frais</CardTitle>
          <CardDescription>
            Au-delà d&apos;un seuil, une validation supplémentaire de la Direction financière est ajoutée
            automatiquement.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={onSubmit}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="nf-montant">Montant ({devise || reference})</Label>
                <div className="flex gap-2">
                  <Input
                    id="nf-montant"
                    type="number"
                    step="0.01"
                    min="0"
                    value={montant}
                    onChange={(e) => setMontant(e.target.value)}
                    className="min-w-0 flex-1"
                    required
                  />
                  <ChampDevise id="nf-devise" valeur={devise || reference} onChange={setDevise} devises={devises} />
                </div>
                <ApercuConversion montant={montant} devise={devise} date={dateDepense} reference={reference} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="nf-categorie">Catégorie</Label>
                <Input
                  id="nf-categorie"
                  placeholder="Transport, Restauration…"
                  value={categorie}
                  onChange={(e) => setCategorie(e.target.value)}
                  required
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nf-date">Date de la dépense</Label>
              <Input
                id="nf-date"
                type="date"
                max={new Date().toISOString().slice(0, 10)}
                value={dateDepense}
                onChange={(e) => setDateDepense(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nf-description">Description</Label>
              <Textarea
                id="nf-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={500}
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nf-recu">Reçu (facultatif)</Label>
              <ChampFichier
                key={cleRecu}
                id="nf-recu"
               
                accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                onChange={(e) => setRecu(e.target.files?.[0] ?? null)}
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
                <Label htmlFor="nf-motif">Motif de la dérogation</Label>
                <Textarea
                  id="nf-motif"
                  value={motif}
                  onChange={(e) => setMotif(e.target.value)}
                  maxLength={1000}
                />
              </div>
            )}

            {erreur && <Alert variant="destructive">{erreur}</Alert>}
            {succes && <Alert variant="success">{succes}</Alert>}
            {avertissement && <Alert>{avertissement}</Alert>}
            {succes && (
              <Link href="/mes-demandes?type=notes_frais" className="text-center text-[13px] font-medium text-accent-text hover:underline">
                Suivre ma note de frais dans « Mes demandes »
              </Link>
            )}

            <Button type="submit" className="h-10 w-full" disabled={enCours}>
              {enCours ? "Envoi…" : "Soumettre la note de frais"}
            </Button>
          </form>
        </CardContent>
      </Card>

    </div>
  );
}
