"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

export const CLE_THEME = "theme";

type Theme = "light" | "dark";

/** Script injecte dans <head> : applique le choix memorise AVANT l'affichage (pas d'eclair de mauvais theme). */
export const SCRIPT_THEME = `try{var t=localStorage.getItem("${CLE_THEME}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

function themeEffectif(): Theme {
  const choisi = document.documentElement.getAttribute("data-theme");
  if (choisi === "light" || choisi === "dark") return choisi;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Bascule claire / sombre. Sans choix memorise, l'ecran suit le systeme ; au premier clic le choix est
 * enregistre (localStorage, best-effort : un navigateur qui le refuse garde le choix pour la session).
 * L'icone est pilotee par le CSS (jeton du theme courant), donc correcte des le premier affichage.
 */
export function BoutonTheme({ className }: { className?: string }) {
  const [theme, setTheme] = React.useState<Theme | null>(null);

  React.useEffect(() => {
    setTheme(themeEffectif());
  }, []);

  function basculer() {
    const suivant: Theme = themeEffectif() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", suivant);
    try {
      localStorage.setItem(CLE_THEME, suivant);
    } catch {
      /* stockage indisponible : le choix vaut pour la session */
    }
    setTheme(suivant);
  }

  const libelle =
    theme === "dark" ? "Passer en mode clair" : theme === "light" ? "Passer en mode sombre" : "Changer de thème";

  return (
    <button
      type="button"
      onClick={basculer}
      aria-label={libelle}
      title={libelle}
      className={cn(
        "flex h-9 w-9 items-center justify-center rounded-full border border-line-strong bg-surface text-ink-dim shadow-sm",
        "transition hover:border-accent hover:text-accent-text hover:shadow-md active:scale-95",
        className
      )}
    >
      <Moon className="theme-lune h-[17px] w-[17px]" strokeWidth={1.8} aria-hidden="true" />
      <Sun className="theme-soleil h-[17px] w-[17px]" strokeWidth={1.8} aria-hidden="true" />
    </button>
  );
}
