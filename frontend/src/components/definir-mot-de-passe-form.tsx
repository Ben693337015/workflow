"use client";

import { Marque } from "@/components/marque";
import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Alert,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { ApiError, definirMotDePasse } from "@/lib/api";

export function DefinirMotDePasseForm({
  mode,
  jeton,
}: {
  mode: "invitation" | "reinitialisation";
  jeton: string;
}) {
  const router = useRouter();
  const { ouvrirSession } = useAuth();
  const [motDePasse, setMotDePasse] = React.useState("");
  const [confirmation, setConfirmation] = React.useState("");
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);

  const titre = mode === "invitation" ? "Activer votre compte" : "Réinitialiser votre mot de passe";
  const description =
    mode === "invitation"
      ? "Choisissez le mot de passe de votre compte sur la plateforme."
      : "Choisissez un nouveau mot de passe pour votre compte.";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErreur(null);
    if (!jeton) {
      setErreur("Lien invalide : jeton manquant.");
      return;
    }
    if (motDePasse.length < 8) {
      setErreur("Le mot de passe doit contenir au moins 8 caractères.");
      return;
    }
    if (motDePasse !== confirmation) {
      setErreur("Les deux mots de passe ne correspondent pas.");
      return;
    }
    setEnCours(true);
    try {
      await definirMotDePasse(jeton, motDePasse);
      // Connecte immediatement : le proxy a deja pose les cookies de session, precisement pour eviter
      // une etape de connexion supplementaire apres le clic sur le lien.
      await ouvrirSession();
      router.replace("/mes-demandes");
    } catch (err) {
      setErreur(
        err instanceof ApiError
          ? "Ce lien est invalide, a expiré, ou a déjà été utilisé. Demandez-en un nouveau si nécessaire."
          : "Une erreur est survenue."
      );
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-sidebar px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-8 flex flex-col items-center text-center">
          <Marque className="mb-3 h-9 w-9 rounded-xl [&>svg]:h-5 [&>svg]:w-5" />
          <p className="text-[15px] font-semibold text-sidebar-ink">Plateforme Workflows</p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>{titre}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={onSubmit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mot-de-passe">Nouveau mot de passe</Label>
                <Input
                  id="mot-de-passe"
                  type="password"
                  value={motDePasse}
                  onChange={(e) => setMotDePasse(e.target.value)}
                  minLength={8}
                  required
                  autoFocus
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="confirmation">Confirmer le mot de passe</Label>
                <Input
                  id="confirmation"
                  type="password"
                  value={confirmation}
                  onChange={(e) => setConfirmation(e.target.value)}
                  required
                />
              </div>
              {erreur && <Alert variant="destructive">{erreur}</Alert>}
              <Button type="submit" disabled={enCours} className="mt-2 h-10">
                {enCours ? "Enregistrement…" : "Valider"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
