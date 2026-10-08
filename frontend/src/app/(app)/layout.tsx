"use client";

import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import { Menu } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Sidebar } from "@/components/layout/sidebar";
import { BoutonTheme } from "@/components/bouton-theme";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { connecte, chargement } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [menuOuvert, setMenuOuvert] = React.useState(false);
  const zoneContenu = React.useRef<HTMLElement>(null);

  // La zone de contenu est desormais le SEUL element qui defile (et non plus la fenetre) : le navigateur ne
  // remet donc plus tout seul la page en haut quand on change d'ecran. On le fait ici.
  React.useEffect(() => {
    zoneContenu.current?.scrollTo?.({ top: 0 });
  }, [pathname]);

  React.useEffect(() => {
    if (!chargement && !connecte) router.replace("/login");
  }, [chargement, connecte, router]);

  if (chargement) {
    return <p className="p-8 text-center text-[13.5px] text-ink-dim">Chargement…</p>;
  }
  if (!connecte) return null;

  // Cadre de la hauteur de l'ecran, qui ne defile jamais : barre laterale et bandeau restent fixes, seule
  // la zone <main> defile.
  return (
    <div className="flex h-dvh overflow-hidden fond-app">
      <Sidebar mobileOpen={menuOuvert} onClose={() => setMenuOuvert(false)} />

      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Bandeau mobile uniquement (sous md) : bouton hamburger + marque,
            remplace la sidebar toujours visible qui n'existe qu'a partir de
            md sur cet ecran. */}
        <header className="flex shrink-0 items-center gap-3 border-b border-line bg-surface px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setMenuOuvert(true)}
            aria-label="Ouvrir le menu"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-ink-dim hover:bg-canvas"
          >
            <Menu className="h-5 w-5" strokeWidth={1.8} />
          </button>
          <p className="text-[14px] font-semibold text-ink">Plateforme Workflows</p>
          <BoutonTheme className="ml-auto" />
        </header>

        {/* Bascule claire / sombre : coin haut droit, flottante, toujours visible (le contenu defile dessous). */}
        <BoutonTheme className="absolute right-5 top-4 z-20 hidden md:flex" />

        <main
          ref={zoneContenu}
          className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-auto px-4 py-6 md:px-8 md:py-8"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
