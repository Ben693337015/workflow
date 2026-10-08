"use client";

import { BoutonTheme } from "@/components/bouton-theme";
import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/form";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";
import { Marque } from "@/components/marque";

/**
 * Bug reel trouve et corrige (verification post-migration) : cette page
 * etait aussi embarquee telle quelle dans DecisionPage (approbateur non
 * connecte cliquant le lien de decision par e-mail, Option B section 9.1).
 * La redirection automatique vers /mes-demandes des que `connecte` passe a
 * true (ci-dessous) faisait perdre le jeton de decision en cours : une fois
 * connecte, l'approbateur n'atterrissait plus jamais sur l'ecran de
 * decision qu'il venait d'ouvrir.
 *
 * `redirigerApresConnexion` (true par defaut, pour la route /login
 * autonome) desactive cette redirection quand la page est montee a
 * l'interieur d'un autre ecran : le parent (ici DecisionPage) se
 * re-affiche naturellement une fois `connecte` a true, sans navigation.
 */
export default function LoginPage({
  redirigerApresConnexion = true,
}: {
  redirigerApresConnexion?: boolean;
}) {
  const router = useRouter();
  const { seConnecter, connecte, chargement: chargementSession } = useAuth();
  const [email, setEmail] = React.useState("");
  const [motDePasse, setMotDePasse] = React.useState("");
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [enCours, setEnCours] = React.useState(false);

  React.useEffect(() => {
    if (redirigerApresConnexion && !chargementSession && connecte) {
      router.replace("/mes-demandes");
    }
  }, [redirigerApresConnexion, chargementSession, connecte, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErreur(null);
    setEnCours(true);
    try {
      await seConnecter(email, motDePasse);
      if (redirigerApresConnexion) router.replace("/mes-demandes");
      // Sinon (embarquee dans DecisionPage) : ne pas naviguer, le parent
      // se charge de reafficher le bon ecran une fois `connecte` a true.
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Une erreur est survenue.");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center bg-sidebar px-4">
      <BoutonTheme className="absolute right-4 top-4" />
      <div className="w-full max-w-[380px]">
        <div className="mb-8 flex flex-col items-center text-center">
          <Marque className="mb-3 h-9 w-9 rounded-xl [&>svg]:h-5 [&>svg]:w-5" />
          <p className="text-[15px] font-semibold text-sidebar-ink">Plateforme Workflows</p>
          <p className="mt-1 text-[13px] text-sidebar-dim">Congés · Notes de frais · Achats</p>
        </div>

        <div className="rounded-2xl border border-sidebar-line bg-surface p-7 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.5)]">
          <h1 className="mb-1 titre-page text-[22px]">Connexion</h1>
          <p className="mb-6 text-[13.5px] text-ink-dim">Accédez à votre espace de demandes.</p>

          <form className="flex flex-col gap-4" onSubmit={onSubmit}>
            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-medium text-ink-dim">E-mail</span>
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-[13.5px] text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-medium text-ink-dim">Mot de passe</span>
              <input
                type="password"
                autoComplete="current-password"
                value={motDePasse}
                onChange={(e) => setMotDePasse(e.target.value)}
                required
                className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-[13.5px] text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
              />
            </label>

            {erreur && <Alert variant="destructive">{erreur}</Alert>}

            <Button type="submit" disabled={enCours} className="mt-2 h-10 w-full">
              {enCours ? "Connexion…" : "Se connecter"}
            </Button>

            <a
              href="/mot-de-passe-oublie"
              className="text-center text-[12.5px] text-ink-dim hover:text-accent"
            >
              Mot de passe oublié ?
            </a>
          </form>
        </div>
      </div>
    </div>
  );
}
