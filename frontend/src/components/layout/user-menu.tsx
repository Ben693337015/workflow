"use client";

import { ChevronDown, LogOut, User as UserIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { libelleRole } from "@/lib/roles";
import type { RoleUtilisateur } from "@/types";

type Utilisateur = {
  nom_complet: string;
  email: string;
  role: RoleUtilisateur;
};

function initiales(nomComplet: string) {
  const mots = nomComplet.trim().split(/\s+/);
  return (mots[0]?.[0] ?? "") + (mots[1]?.[0] ?? "");
}

export function UserMenu({
  utilisateur,
  onDeconnexion,
}: {
  utilisateur: Utilisateur;
  onDeconnexion: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex w-full min-w-0 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-sidebar-active"
          aria-label="Menu du profil"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/20 text-[12.5px] font-semibold text-accent-text">
            {initiales(utilisateur.nom_complet).toUpperCase()}
          </span>
          <span className="flex min-w-0 flex-1 flex-col leading-tight">
            <span className="truncate text-[13.5px] font-medium text-sidebar-ink" title={utilisateur.nom_complet}>
              {utilisateur.nom_complet}
            </span>
            <span className="truncate text-[11.5px] text-sidebar-dim">
              {libelleRole(utilisateur.role)}
            </span>
          </span>
          <ChevronDown className="h-4 w-4 shrink-0 text-sidebar-dim" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent>
        <DropdownMenuLabel>
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[13px] font-semibold text-accent-text">
              {initiales(utilisateur.nom_complet).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13.5px] font-medium text-ink" title={utilisateur.nom_complet}>
                {utilisateur.nom_complet}
              </p>
              <p className="truncate text-[12px] text-ink-faint" title={utilisateur.email}>{utilisateur.email}</p>
            </div>
          </div>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem>
          <UserIcon className="h-[18px] w-[18px]" strokeWidth={1.8} />
          <span>Mon profil</span>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem destructive onSelect={onDeconnexion}>
          <LogOut className="h-[18px] w-[18px]" strokeWidth={1.8} />
          <span>Déconnexion</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
