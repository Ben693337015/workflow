"use client";

import { SqueletteListe } from "@/components/ui/squelette";
import * as React from "react";
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
import {
  ApiError,
  listerMonEquipe,
  listerTypesConge,
  regulariserDemandeConges,
} from "@/lib/api";
import type { TypeConge, UtilisateurRead } from "@/types";

export default function RegularisationPage() {
  const [equipe, setEquipe] = React.useState<UtilisateurRead[]>([]);
  const [typesConge, setTypesConge] = React.useState<TypeConge[]>([]);
  const [employeId, setEmployeId] = React.useState("");
  const [typeCongeId, setTypeCongeId] = React.useState("");
  const [dateDebut, setDateDebut] = React.useState("");
  const [dateFin, setDateFin] = React.useState("");
  const [action, setAction] = React.useState<"approuver" | "refuser">("approuver");
  const [commentaire, setCommentaire] = React.useState("");
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [succes, setSucces] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);
  const [chargement, setChargement] = React.useState(true);

  React.useEffect(() => {
    Promise.all([listerMonEquipe(), listerTypesConge()])
      .then(([eq, types]) => {
        setEquipe(eq);
        setTypesConge(types);
        if (eq.length > 0) setEmployeId(eq[0].id);
        if (types.length > 0) setTypeCongeId(types[0].id);
      })
      .catch(() => setErreur("Impossible de charger les données nécessaires."))
      .finally(() => setChargement(false));
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErreur(null);
    setSucces(null);
    if (action === "refuser" && !commentaire.trim()) {
      setErreur("Un commentaire est obligatoire en cas de refus.");
      return;
    }
    setEnCours(true);
    try {
      const resultat = await regulariserDemandeConges({
        employe_id: employeId,
        type_conge_id: typeCongeId,
        date_debut: dateDebut,
        date_fin: dateFin,
        action,
        commentaire: commentaire || undefined,
      });
      setSucces(
        `Régularisation enregistrée (${resultat.nombre_jours} jour(s)) — statut : ${resultat.statut_global}.`
      );
      setDateDebut("");
      setDateFin("");
      setCommentaire("");
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Une erreur est survenue.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-lg">
      <h1 className="titre-page mb-6 text-center">Régularisation</h1>
      <Card>
        <CardHeader>
          <CardTitle>Régulariser une absence</CardTitle>
          <CardDescription>
            Crée et décide immédiatement une demande au nom d&apos;un employé (absence
            constatée après coup).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {chargement ? (
            <SqueletteListe />
          ) : (
            <form className="flex flex-col gap-4" onSubmit={onSubmit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="employe">Employé</Label>
                <Select
                  id="employe"
                  value={employeId}
                  onChange={(e) => setEmployeId(e.target.value)}
                  required
                >
                  {equipe.length === 0 && <option value="">Aucun employé rattaché</option>}
                  {equipe.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.nom_complet} ({u.email})
                    </option>
                  ))}
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="type-conge-reg">Type de congé</Label>
                <Select
                  id="type-conge-reg"
                  value={typeCongeId}
                  onChange={(e) => setTypeCongeId(e.target.value)}
                  required
                >
                  {typesConge.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.nom}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="reg-date-debut">Date de début</Label>
                  <Input
                    id="reg-date-debut"
                    type="date"
                    value={dateDebut}
                    onChange={(e) => setDateDebut(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="reg-date-fin">Date de fin</Label>
                  <Input
                    id="reg-date-fin"
                    type="date"
                    value={dateFin}
                    onChange={(e) => setDateFin(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="action">Décision</Label>
                <Select
                  id="action"
                  value={action}
                  onChange={(e) => setAction(e.target.value as "approuver" | "refuser")}
                >
                  <option value="approuver">Approuver</option>
                  <option value="refuser">Refuser</option>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="reg-commentaire">
                  Commentaire {action === "refuser" && "(obligatoire)"}
                </Label>
                <Textarea
                  id="reg-commentaire"
                  value={commentaire}
                  onChange={(e) => setCommentaire(e.target.value)}
                />
              </div>

              {erreur && <Alert variant="destructive">{erreur}</Alert>}
              {succes && <Alert variant="success">{succes}</Alert>}

              <Button type="submit" disabled={enCours || !employeId || !typeCongeId} className="h-10">
                {enCours ? "Enregistrement…" : "Enregistrer la régularisation"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
