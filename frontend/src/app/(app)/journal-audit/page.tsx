"use client";

import * as React from "react";
import { Alert, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label } from "@/components/ui/form";
import { TableScroll } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { ApiError, consulterJournal, listerActionsAudit } from "@/lib/api";
import { formaterHorodatage } from "@/lib/dates";
import type { ActionAudit, AuditPage, RoleUtilisateur } from "@/types";

const TAILLE_PAGE = 25;
const ROLES_AUTORISES: RoleUtilisateur[] = ["drh", "direction_generale", "controleur_de_gestion"];

/** Resume lisible du detail d'une entree : "cle : valeur", avec "avant -> apres" pour les modifications. */
export function resumerDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([cle, valeur]) => {
      if (valeur && typeof valeur === "object") {
        const objet = valeur as Record<string, unknown>;
        const morceaux = Object.entries(objet).map(([sous, v]) =>
          v && typeof v === "object" && "avant" in (v as object)
            ? `${sous} : ${String((v as { avant: unknown }).avant)} → ${String((v as { apres: unknown }).apres)}`
            : `${sous} : ${String(v)}`
        );
        return `${cle} (${morceaux.join(", ")})`;
      }
      return `${cle} : ${String(valeur)}`;
    })
    .join(" · ");
}

/** Debut / fin de journee UTC pour un champ date (yyyy-mm-dd). */
function borne(date: string, fin: boolean): string | undefined {
  return date ? `${date}T${fin ? "23:59:59.999" : "00:00:00"}Z` : undefined;
}

/**
 * Journal d'audit (CDC fonctionnel 2.4 : "qui a fait quoi, et quand"). Consultation seule : le
 * journal est inalterable (declencheurs en base), aucune action de modification n'existe ici.
 * Reserve a la DRH, a la Direction generale et au Controleur de gestion (le backend le verifie).
 */
export default function JournalAuditPage() {
  const { utilisateur } = useAuth();
  const autorise = !!utilisateur && ROLES_AUTORISES.includes(utilisateur.role);

  const [actions, setActions] = React.useState<ActionAudit[]>([]);
  const [action, setAction] = React.useState("");
  const [depuis, setDepuis] = React.useState("");
  const [jusquA, setJusquA] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [page, setPage] = React.useState<AuditPage | null>(null);
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [chargement, setChargement] = React.useState(false);

  React.useEffect(() => {
    if (!autorise) return;
    listerActionsAudit().then(setActions).catch(() => setActions([]));
  }, [autorise]);

  const charger = React.useCallback(() => {
    setChargement(true);
    setErreur(null);
    consulterJournal({
      action: action || undefined,
      depuis: borne(depuis, false),
      jusqu_a: borne(jusquA, true),
      limit: TAILLE_PAGE,
      offset,
    })
      .then(setPage)
      .catch((err) => setErreur(err instanceof ApiError ? err.message : "Impossible de charger le journal."))
      .finally(() => setChargement(false));
  }, [action, depuis, jusquA, offset]);

  React.useEffect(() => {
    if (autorise) charger();
  }, [autorise, charger]);

  function filtrer<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setOffset(0); // un nouveau filtre repart de la premiere page
    };
  }

  if (!autorise) {
    return (
      <div className="max-w-3xl">
        <Alert variant="destructive">
          Le journal d&apos;audit est réservé à la DRH, à la Direction générale et au Contrôleur de gestion.
        </Alert>
      </div>
    );
  }

  const debut = page && page.total > 0 ? page.offset + 1 : 0;
  const fin = page ? Math.min(page.offset + page.limit, page.total) : 0;

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <h1 className="titre-page">Journal d&apos;audit</h1>

      <Card>
        <CardHeader>
          <CardTitle>Traçabilité des actions</CardTitle>
          <CardDescription>
            Chaque action est consignée avec son auteur et son horodatage exact. Le journal est en ajout seul :
            il ne peut être ni modifié ni supprimé.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="audit-action">Action</Label>
              <select
                id="audit-action"
                value={action}
                onChange={(e) => filtrer(setAction)(e.target.value)}
                className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-[13.5px] text-ink"
              >
                <option value="">Toutes les actions</option>
                {actions.map((a) => (
                  <option key={a.action} value={a.action}>
                    {a.libelle}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="audit-depuis">Du</Label>
              <Input id="audit-depuis" type="date" value={depuis} onChange={(e) => filtrer(setDepuis)(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="audit-jusqua">Au</Label>
              <Input id="audit-jusqua" type="date" value={jusquA} onChange={(e) => filtrer(setJusquA)(e.target.value)} />
            </div>
          </div>

          {erreur && <Alert variant="destructive">{erreur}</Alert>}

          <div className="overflow-x-auto">
            <TableScroll>
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                  <th className="py-2.5 pr-3 font-medium">Date</th>
                  <th className="py-2.5 pr-3 font-medium">Action</th>
                  <th className="py-2.5 pr-3 font-medium">Auteur</th>
                  <th className="py-2.5 pr-3 font-medium">Cible</th>
                  <th className="py-2.5 font-medium">Détails</th>
                </tr>
              </thead>
              <tbody>
                {page && page.elements.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-4 text-ink-faint">
                      Aucune entrée pour ces critères.
                    </td>
                  </tr>
                )}
                {page?.elements.map((e) => (
                  <tr key={e.id} className="border-b border-line align-top last:border-0">
                    <td className="whitespace-nowrap py-2.5 pr-3 text-ink-dim">{formaterHorodatage(e.horodate_le)}</td>
                    <td className="cell-texte py-2.5 pr-3 font-medium text-ink">{e.libelle}</td>
                    <td className="cell-texte py-2.5 pr-3 text-ink-dim">{e.acteur_nom}</td>
                    <td className="whitespace-nowrap py-2.5 pr-3 text-ink-dim">
                      {e.cible_type}
                      {e.cible_id ? ` · ${e.cible_id.slice(0, 8)}` : ""}
                    </td>
                    <td className="cell-texte py-2.5 text-ink-dim">{resumerDetails(e.details)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </TableScroll>
          </div>

          <div className="flex items-center justify-between text-[13px] text-ink-dim">
            <span>{page ? `${debut}–${fin} sur ${page.total}` : chargement ? "Chargement…" : ""}</span>
            <div className="flex gap-2">
              <Button variant="outline" disabled={offset === 0 || chargement} onClick={() => setOffset(Math.max(0, offset - TAILLE_PAGE))}>
                Précédent
              </Button>
              <Button
                variant="outline"
                disabled={!page || offset + TAILLE_PAGE >= page.total || chargement}
                onClick={() => setOffset(offset + TAILLE_PAGE)}
              >
                Suivant
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
