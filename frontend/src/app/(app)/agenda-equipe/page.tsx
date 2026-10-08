"use client";

import * as React from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Alert,
} from "@/components/ui/form";
import { Badge } from "@/components/ui/badge";
import { ApiError, listerAgendaEquipe } from "@/lib/api";
import type { AgendaEquipeEvenement } from "@/types";

export default function AgendaEquipePage() {
  const [evenements, setEvenements] = React.useState<AgendaEquipeEvenement[]>([]);
  const [chargement, setChargement] = React.useState(true);
  const [erreur, setErreur] = React.useState<string | null>(null);

  React.useEffect(() => {
    listerAgendaEquipe()
      .then(setEvenements)
      .catch((err) => setErreur(err instanceof ApiError ? err.message : "Impossible de charger l'agenda."))
      .finally(() => setChargement(false));
  }, []);

  if (chargement) {
    return <p className="text-[13.5px] text-ink-dim">Chargement de l&apos;agenda…</p>;
  }

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <h1 className="titre-page">Agenda de l&apos;équipe</h1>
      {erreur && <Alert variant="destructive">{erreur}</Alert>}

      <Card>
        <CardHeader>
          <CardTitle>Absences approuvées</CardTitle>
          <CardDescription>
            Calculé à partir des demandes déjà approuvées — aucune saisie séparée à maintenir.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {evenements.length === 0 && (
            <p className="text-[13px] text-ink-faint">Aucune absence approuvée pour l&apos;instant.</p>
          )}
          {evenements.map((e) => (
            <div
              key={e.demande_id}
              className="flex items-center justify-between rounded-lg border border-line px-3.5 py-2.5"
            >
              <span className="text-[13.5px] font-medium text-ink">{e.employe_nom}</span>
              <Badge variant="secondary">
                Du {e.date_debut} au {e.date_fin}
              </Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
