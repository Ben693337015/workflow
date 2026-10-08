"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays,
  CalendarRange,
  ClipboardList,
  Receipt,
  ScrollText,
  Coins,
  ShoppingCart,
  ShieldCheck,
  Stamp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { UserMenu } from "@/components/layout/user-menu";
import { Marque } from "@/components/marque";

const liens = [
  { href: "/mes-demandes", label: "Mes demandes", icon: ClipboardList },
  { href: "/nouvelle-demande", label: "Nouvelle demande", icon: CalendarDays },
  { href: "/notes-frais", label: "Notes de frais", icon: Receipt },
  { href: "/achats", label: "Achats", icon: ShoppingCart },
  { href: "/regularisation", label: "Régularisation", icon: Stamp, roles: ["manager", "drh"] },
  { href: "/agenda-equipe", label: "Agenda équipe", icon: CalendarRange, roles: ["manager", "drh"] },
  { href: "/admin", label: "Administration", icon: ShieldCheck, roles: ["drh"] },
  {
    href: "/journal-audit",
    label: "Journal d'audit",
    icon: ScrollText,
    roles: ["drh", "direction_generale", "controleur_de_gestion"],
  },
  {
    href: "/synthese-frais",
    label: "Synthèse des frais",
    icon: Coins,
    roles: ["drh", "direction_financiere", "controleur_de_gestion"],
  },
];

/**
 * Sidebar - drawer coulissant sous le breakpoint md (768px), fixe et
 * toujours visible au-dessus. Reprend le meme principe que la correction
 * apportee au bandeau horizontal de l'ancien frontend Vite (menu hamburger
 * repliable) : au-dessus de md le comportement est celui d'une sidebar
 * classique inchangee ; en dessous, elle devient un panneau qui coulisse
 * depuis la gauche, controle par AppLayout (etat menuOuvert), avec un fond
 * assombri cliquable pour se refermer.
 */
export function Sidebar({
  mobileOpen,
  onClose,
}: {
  mobileOpen: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();
  const { utilisateur, seDeconnecter } = useAuth();

  if (!utilisateur) return null;

  const liensVisibles = liens.filter((l) => !l.roles || l.roles.includes(utilisateur.role));

  return (
    <>
      {/* Fond assombri, mobile uniquement, quand le tiroir est ouvert */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex h-dvh w-64 shrink-0 flex-col bg-sidebar px-3 py-4",
          "transition-transform duration-200 ease-out",
          "md:static md:h-full md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Marque + navigation : cette zone defile seule si l'ecran est trop court pour tous les liens, et le
            menu utilisateur en dessous reste toujours visible. */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-6 flex shrink-0 items-center gap-2.5 px-2.5 py-1.5">
            <Marque />
            <div className="min-w-0">
              <p className="truncate text-[14.5px] font-semibold text-sidebar-ink">Plateforme Workflows</p>
              <p className="text-[11.5px] text-balance leading-snug text-sidebar-dim">Congés · Notes de frais · Achats</p>
            </div>
          </div>

          <nav className="flex min-h-0 flex-col gap-0.5 overflow-y-auto overscroll-contain">
            {liensVisibles.map(({ href, label, icon: Icon }) => {
              const actif = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={onClose}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
                    actif
                      ? "bg-sidebar-active text-sidebar-ink"
                      : "text-sidebar-dim hover:bg-sidebar-active/60 hover:text-sidebar-ink"
                  )}
                >
                  <Icon className="h-[17px] w-[17px] shrink-0" strokeWidth={1.8} />
                  <span className="min-w-0 truncate">{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="shrink-0 border-t border-sidebar-line pt-3">
          <UserMenu utilisateur={utilisateur} onDeconnexion={seDeconnecter} />
        </div>
      </aside>
    </>
  );
}
