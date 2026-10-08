"use client";

import * as React from "react";
import { Download, Paperclip } from "lucide-react";
import { Alert, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label } from "@/components/ui/form";
import { TableScroll } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { ApiError, exporterSyntheseCsv, syntheseNotesDeFrais } from "@/lib/api";
import { enregistrerFichier } from "@/lib/telechargement";
import { formaterAvecEquivalent } from "@/lib/montants";
import type { RoleUtilisateur, SyntheseFrais } from "@/types";

const TAILLE_PAGE = 25;
const ROLES_AUTORISES: RoleUtilisateur[] = ["drh", "direction_financiere", "controleur_de_gestion"];

/**
 * Synthèse des notes de frais validées, transmise à la comptabilité (CDC fonctionnel 3 : "tableau de
 * synthèse des frais validés transmis à la comptabilité pour remboursement"). Un e-mail part aussi à
 * chaque validation finale ; cet écran couvre le tableau et l'export CSV. Réservé à la DRH, la
 * Direction financière et le Contrôleur de gestion (le backend le vérifie).
 */
export default function SyntheseFraisPage() {
  const { utilisateur } = useAuth();
  const autorise = !!utilisateur && ROLES_AUTORISES.includes(utilisateur.role);

  const [service, setService] = React.useState("");
  const [depuis, setDepuis] = React.useState("");
  const [jusquA, setJusquA] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [page, setPage] = React.useState<SyntheseFrais | null>(null);
  const [erreur, setErreur] = React.useState<string | null>(null);
  const [chargement, setChargement] = React.useState(false);
  const [export_, setExport] = React.useState(false);

  const filtres = React.useMemo(
    () => ({ depuis: depuis || undefined, jusqu_a: jusquA || undefined, service: service.trim() || undefined }),
    [depuis, jusquA, service]
  );

  const charger = React.useCallback(() => {
    setChargement(true);
    setErreur(null);
    syntheseNotesDeFrais({ ...filtres, limit: TAILLE_PAGE, offset })
      .then(setPage)
      .catch((err) => setErreur(err instanceof ApiError ? err.message : "Impossible de charger la synthèse."))
      .finally(() => setChargement(false));
  }, [filtres, offset]);

  React.useEffect(() => {
    if (autorise) charger();
  }, [autorise, charger]);

  function filtrer<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setOffset(0);
    };
  }

  async function exporter() {
    setErreur(null);
    setExport(true);
    try {
      const blob = await exporterSyntheseCsv(filtres);
      enregistrerFichier(blob, `synthese-notes-de-frais-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Export impossible.");
    } finally {
      setExport(false);
    }
  }

  if (!autorise) {
    return (
      <div className="max-w-3xl">
        <Alert variant="destructive">
          La synthèse des notes de frais est réservée à la DRH, à la Direction financière et au Contrôleur de gestion.
        </Alert>
      </div>
    );
  }

  const debut = page && page.nombre > 0 ? offset + 1 : 0;
  const fin = page ? Math.min(offset + TAILLE_PAGE, page.nombre) : 0;

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <h1 className="titre-page">Synthèse des notes de frais</h1>

      <Card>
        <CardHeader>
          <CardTitle>Notes de frais validées</CardTitle>
          <CardDescription>
            Notes déjà validées, prêtes pour remboursement. Un e-mail est aussi envoyé à chaque validation finale.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="synthese-depuis">Validée du</Label>
              <Input id="synthese-depuis" type="date" value={depuis} onChange={(e) => filtrer(setDepuis)(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="synthese-jusqua">Au</Label>
              <Input id="synthese-jusqua" type="date" value={jusquA} onChange={(e) => filtrer(setJusquA)(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="synthese-service">Service</Label>
              <Input id="synthese-service" value={service} onChange={(e) => filtrer(setService)(e.target.value)} placeholder="Tous" />
            </div>
            <div className="flex items-end">
              <Button variant="outline" disabled={export_} onClick={exporter} className="w-full gap-1.5">
                <Download className="h-4 w-4" />
                Exporter en CSV
              </Button>
            </div>
          </div>

          {erreur && <Alert variant="destructive">{erreur}</Alert>}

          {page && page.par_devise.length > 0 && (
            <div className="flex flex-wrap gap-4 rounded-lg bg-canvas p-3 text-[13px]">
              {page.par_devise.map((t) => (
                <span key={t.devise} className="text-ink-dim">
                  <strong className="text-ink">{t.nombre}</strong> en {t.devise}
                  {t.devise !== page.devise_reference && ` (≈ ${t.total_reference} ${page.devise_reference})`}
                </span>
              ))}
              <span className="ml-auto font-medium text-ink">
                Total : {page.total_reference} {page.devise_reference}
              </span>
            </div>
          )}

          <div className="overflow-x-auto">
            <TableScroll>
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                  <th className="py-2.5 pr-3 font-medium">Validée le</th>
                  <th className="py-2.5 pr-3 font-medium">Demandeur</th>
                  <th className="py-2.5 pr-3 font-medium">Catégorie</th>
                  <th className="py-2.5 pr-3 font-medium">Montant</th>
                  <th className="py-2.5 pr-3 font-medium">Validé par</th>
                  <th className="py-2.5 font-medium">Pièces</th>
                </tr>
              </thead>
              <tbody>
                {page && page.elements.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-4 text-ink-faint">
                      Aucune note de frais validée pour ces critères.
                    </td>
                  </tr>
                )}
                {page?.elements.map((l) => (
                  <tr key={l.id} className="border-b border-line align-top last:border-0">
                    <td className="whitespace-nowrap py-2.5 pr-3 text-ink-dim">
                      {l.valide_le ? new Date(l.valide_le).toLocaleDateString("fr-FR") : "—"}
                    </td>
                    <td className="cell-texte py-2.5 pr-3 text-ink">
                      {l.demandeur_nom}
                      <div className="text-[12px] text-ink-faint">{l.service}</div>
                    </td>
                    <td className="cell-texte py-2.5 pr-3 text-ink-dim">
                      {l.categorie}
                      {l.derogation && <div className="text-[12px] text-warn">Dérogation</div>}
                    </td>
                    <td className="cell-fixe py-2.5 pr-3 font-medium text-ink">
                      {formaterAvecEquivalent(l.montant, l.devise, l.montant_reference, page?.devise_reference ?? "EUR")}
                    </td>
                    <td className="cell-texte py-2.5 pr-3 text-ink-dim">{l.valide_par.join(", ") || "—"}</td>
                    <td className="py-2.5 text-ink-dim">
                      {l.nb_pieces > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <Paperclip className="h-3.5 w-3.5" />
                          {l.nb_pieces}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </TableScroll>
          </div>

          <div className="flex items-center justify-between text-[13px] text-ink-dim">
            <span>{page ? `${debut}–${fin} sur ${page.nombre}` : chargement ? "Chargement…" : ""}</span>
            <div className="flex gap-2">
              <Button variant="outline" disabled={offset === 0 || chargement} onClick={() => setOffset(Math.max(0, offset - TAILLE_PAGE))}>
                Précédent
              </Button>
              <Button
                variant="outline"
                disabled={!page || offset + TAILLE_PAGE >= page.nombre || chargement}
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
