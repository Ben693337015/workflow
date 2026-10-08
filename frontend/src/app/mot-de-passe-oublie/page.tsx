"use client";

import { Marque } from "@/components/marque";
import * as React from "react";
import Link from "next/link";
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
import { demanderReinitialisation } from "@/lib/api";

export default function MotDePasseOubliePage() {
  const [email, setEmail] = React.useState("");
  const [envoye, setEnvoye] = React.useState(false);
  const [enCours, setEnCours] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEnCours(true);
    try {
      await demanderReinitialisation(email);
    } finally {
      // Reponse volontairement identique que le compte existe ou non
      // (anti-enumeration, section 5 du CDC) : le frontend ne doit jamais
      // distinguer les deux cas, y compris en cas d'erreur reseau.
      setEnvoye(true);
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
        <Card className="p-1">
          <CardHeader>
            <CardTitle>Mot de passe oublié</CardTitle>
            <CardDescription>Recevez un lien pour choisir un nouveau mot de passe.</CardDescription>
          </CardHeader>
          <CardContent>
            {envoye ? (
              <Alert variant="success">
                Si un compte existe pour cet e-mail, un lien de réinitialisation vient d&apos;être
                envoyé.
              </Alert>
            ) : (
              <form className="flex flex-col gap-4" onSubmit={onSubmit}>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="email">E-mail</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
                <Button type="submit" disabled={enCours} className="mt-2 h-10">
                  {enCours ? "Envoi…" : "Envoyer le lien"}
                </Button>
              </form>
            )}
            <p className="mt-4 text-center text-[12.5px] text-ink-dim">
              <Link href="/login" className="underline hover:text-accent">
                Retour à la connexion
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
