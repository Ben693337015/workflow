"use client";

import { ChampFichier } from "@/components/champ-fichier";
import * as React from "react";
import { messageTailleFichier } from "@/lib/fichiers";
import { useRouter } from "next/navigation";
import { CalendarDays } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  Textarea,
  Alert,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { ApiError, deposerPieceJointe, listerTypesConge, soumettreDemandeConges } from "@/lib/api";
import type { TypeConge } from "@/types";

export default function NouvelleDemandePage() {
  const router = useRouter();
  const [typesConge, setTypesConge] = React.useState<TypeConge[]>([]);
  const [typeCongeId, setTypeCongeId] = React.useState("");
  const [dateDebut, setDateDebut] = React.useState("");
  const [dateFin, setDateFin] = React.useState("");
  const [commentaire, setCommentaire] = React.useState("");
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [succes, setSucces] = React.useState<string | null>(null);
  const [avertissement, setAvertissement] = React.useState<string | null>(null);
  const [justificatif, setJustificatif] = React.useState<File | null>(null);
  const [cleJustificatif, setCleJustificatif] = React.useState(0);
  const [enCours, setEnCours] = React.useState(false);

  React.useEffect(() => {
    listerTypesConge()
      .then((types) => {
        setTypesConge(types);
        if (types.length > 0) setTypeCongeId(types[0].id);
      })
      .catch(() => setErreur("Impossible de charger les types de congé."));
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErreur(null);
    setSucces(null);
    setAvertissement(null);

    const tropGros = messageTailleFichier(justificatif);
    if (tropGros) {
      setErreur(tropGros);
      return;
    }

    if (dateFin < dateDebut) {
      setErreur("La date de fin doit être postérieure ou égale à la date de début.");
      return;
    }

    setEnCours(true);
    try {
      const resultat = await soumettreDemandeConges({
        type_conge_id: typeCongeId,
        date_debut: dateDebut,
        date_fin: dateFin,
        commentaire: commentaire.trim() || undefined,
      });
      setSucces(
        `Demande soumise avec succès (${resultat.nombre_jours} jour(s) décompté(s), jours fériés exclus). ` +
          "Le manager a été notifié."
      );
      setDateDebut("");
      setDateFin("");
      setCommentaire("");
      // Justificatif facultatif : la demande existe d'abord, la piece s'y attache ensuite. Un echec
      // d'envoi ne remet pas en cause la demande soumise : on l'indique et on ne redirige pas, pour
      // que l'avertissement reste lisible (le justificatif s'ajoute depuis "Mes demandes").
      let depotEchoue = false;
      if (justificatif) {
        try {
          await deposerPieceJointe(resultat.id, justificatif);
        } catch (err) {
          depotEchoue = true;
          setAvertissement(
            `Demande soumise, mais le justificatif n'a pas pu être envoyé (${err instanceof ApiError ? err.message : "erreur"}). ` +
              "Vous pourrez l'ajouter depuis « Mes demandes »."
          );
        }
      }
      setJustificatif(null);
      setCleJustificatif((n) => n + 1);
      if (!depotEchoue) setTimeout(() => router.push("/mes-demandes"), 1200);
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Une erreur est survenue.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-xl">
      <h1 className="titre-page mb-6 text-center">Nouvelle demande</h1>
      <Card className="border-t-2 border-t-accent">
        <CardHeader>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent-text">
              <CalendarDays className="h-5 w-5" strokeWidth={1.8} />
            </span>
            <div>
              <CardTitle>Nouvelle demande de congé</CardTitle>
              <CardDescription>
                Le solde disponible et les jours fériés sont vérifiés automatiquement à la
                soumission.
              </CardDescription>
            </div>
          </div>
        </CardHeader>

        <CardContent>
          <form className="flex flex-col gap-5" onSubmit={onSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="type-conge">Type de congé</Label>
              <Select
                id="type-conge"
                value={typeCongeId}
                onChange={(e) => setTypeCongeId(e.target.value)}
                required
              >
                {typesConge.length === 0 && <option value="">Chargement…</option>}
                {typesConge.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nom}
                  </option>
                ))}
              </Select>
            </div>

            <div className="grid grid-cols-1 gap-4 rounded-lg bg-canvas p-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="date-debut">Date de début</Label>
                <Input
                  id="date-debut"
                  type="date"
                  value={dateDebut}
                  onChange={(e) => setDateDebut(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="date-fin">Date de fin</Label>
                <Input
                  id="date-fin"
                  type="date"
                  value={dateFin}
                  onChange={(e) => setDateFin(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="commentaire">Commentaire (facultatif)</Label>
              <Textarea
                id="commentaire"
                placeholder="Un contexte utile pour votre manager (facultatif)…"
                value={commentaire}
                onChange={(e) => setCommentaire(e.target.value)}
                maxLength={1000}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="justificatif">Justificatif d&apos;absence (facultatif)</Label>
              <ChampFichier
                key={cleJustificatif}
                id="justificatif"
               
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                onChange={(e) => setJustificatif(e.target.files?.[0] ?? null)}
              />
            </div>

            {erreur && <Alert variant="destructive">{erreur}</Alert>}
            {succes && <Alert variant="success">{succes}</Alert>}
            {avertissement && <Alert>{avertissement}</Alert>}

            <Button type="submit" className="h-10 w-full" disabled={enCours || !typeCongeId}>
              {enCours ? "Envoi…" : "Envoyer la demande"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
