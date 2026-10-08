"use client";

import * as React from "react";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { SqueletteListe } from "@/components/ui/squelette";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/form";
import { TableScroll } from "@/components/ui/table";
import { DiscussionDialog } from "@/components/discussion-dialog";
import { useDevises } from "@/components/champ-devise";
import { ICONES_TYPE, LigneDemandeRow, titreDiscussion } from "@/components/ligne-demande";
import {
  ApiError,
  listerMesDemandesAchat,
  listerMesDemandesConges,
  listerMesNotesDeFrais,
} from "@/lib/api";
import {
  compter,
  filtreDepuisUrl,
  fusionner,
  ORDRE_TYPES,
  TYPES_DEMANDE,
  type LigneDemande,
  type TypeDemande,
} from "@/lib/demandes";
import type { DemandeAchat, DemandeConges, NoteFrais } from "@/types";

type Filtre = TypeDemande | "toutes";

function MesDemandes() {
  const parametres = useSearchParams();
  const [conges, setConges] = React.useState<DemandeConges[]>([]);
  const [notes, setNotes] = React.useState<NoteFrais[]>([]);
  const [achats, setAchats] = React.useState<DemandeAchat[]>([]);
  const [chargement, setChargement] = React.useState(true);
  const [erreurs, setErreurs] = React.useState<string[]>([]);
  const [filtre, setFiltre] = React.useState<Filtre>(() => filtreDepuisUrl(parametres?.get("type")));
  const [discussionOuverte, setDiscussionOuverte] = React.useState<string | null>(null);
  const { reference } = useDevises();

  const charger = React.useCallback(() => {
    setChargement(true);
    // Trois listes independantes : la panne de l'une n'empeche jamais d'afficher les deux autres.
    const message = (err: unknown, defaut: string) => (err instanceof ApiError ? err.message : defaut);
    Promise.allSettled([listerMesDemandesConges(), listerMesNotesDeFrais(), listerMesDemandesAchat()])
      .then(([c, n, a]) => {
        const problemes: string[] = [];
        if (c.status === "fulfilled") setConges(c.value);
        else problemes.push(message(c.reason, "Impossible de charger vos demandes de congés."));
        if (n.status === "fulfilled") setNotes(n.value);
        else problemes.push(message(n.reason, "Impossible de charger vos notes de frais."));
        if (a.status === "fulfilled") setAchats(a.value);
        else problemes.push(message(a.reason, "Impossible de charger vos demandes d'achat."));
        setErreurs(problemes);
      })
      .finally(() => setChargement(false));
  }, []);

  React.useEffect(() => {
    charger();
  }, [charger]);

  const toutes = React.useMemo(() => fusionner(conges, notes, achats), [conges, notes, achats]);
  const nombres = compter(toutes);
  const visibles: LigneDemande[] = filtre === "toutes" ? toutes : toutes.filter((l) => l.type === filtre);
  const ouverte = toutes.find((l) => l.demande.id === discussionOuverte);

  const onglets: { valeur: Filtre; label: string }[] = [
    { valeur: "toutes", label: "Toutes" },
    ...ORDRE_TYPES.map((t) => ({ valeur: t as Filtre, label: TYPES_DEMANDE[t].pluriel })),
  ];

  return (
    <div className="max-w-5xl">
      <div className="mb-7 flex items-start justify-between gap-4">
        <div>
          <h1 className="titre-page">Mes demandes</h1>
          <p className="mt-1 text-[13.5px] text-ink-dim">
            Toutes vos demandes — congés, notes de frais et achats — avec leur état.
          </p>
        </div>
        <Link href="/nouvelle-demande">
          <Button>
            <Plus className="h-4 w-4" />
            Nouvelle demande
          </Button>
        </Link>
      </div>

      {erreurs.map((e) => (
        <div key={e} className="mb-4">
          <Alert variant="destructive">{e}</Alert>
        </div>
      ))}

      <div role="tablist" aria-label="Type de demande" className="mb-4 flex flex-wrap gap-2">
        {onglets.map(({ valeur, label }) => {
          const actif = filtre === valeur;
          const Icone = valeur === "toutes" ? null : ICONES_TYPE[valeur];
          return (
            <button
              key={valeur}
              role="tab"
              aria-selected={actif}
              onClick={() => setFiltre(valeur)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors ${
                actif
                  ? "border-accent bg-accent-soft text-accent-ink"
                  : "border-line bg-surface text-ink-dim hover:bg-canvas hover:text-ink"
              }`}
            >
              {Icone && <Icone className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden="true" />}
              {label}
              <span className={`text-[12px] ${actif ? "text-accent-ink" : "text-ink-faint"}`}>{nombres[valeur]}</span>
            </button>
          );
        })}
      </div>

      {chargement ? (
        <SqueletteListe />
      ) : toutes.length === 0 ? (
        <div className="rounded-xl border border-line bg-surface px-6 py-10 text-center">
          <p className="text-[13.5px] text-ink-dim">Aucune demande pour l&apos;instant.</p>
          <p className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1 text-[13px] text-ink-faint">
            {ORDRE_TYPES.map((t) => (
              <Link key={t} href={TYPES_DEMANDE[t].formulaire} className="font-medium text-accent-text hover:underline">
                {TYPES_DEMANDE[t].lienFormulaire}
              </Link>
            ))}
          </p>
        </div>
      ) : visibles.length === 0 ? (
        <div className="rounded-xl border border-line bg-surface px-6 py-10 text-center">
          <p className="text-[13.5px] text-ink-dim">
            Aucune demande de ce type pour l&apos;instant.
          </p>
          {filtre !== "toutes" && (
            <Link href={TYPES_DEMANDE[filtre].formulaire} className="mt-1 inline-block text-[13px] font-medium text-accent-text hover:underline">
              {TYPES_DEMANDE[filtre].lienFormulaire}
            </Link>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <TableScroll>
            <table className="tableau-cartes w-full text-left text-[13.5px]">
              <thead>
                <tr className="border-b border-line text-[12px] uppercase tracking-wide text-ink-faint">
                  <th className="px-5 py-3 font-medium">Type</th>
                  <th className="px-5 py-3 font-medium">Demande</th>
                  <th className="px-5 py-3 font-medium">Statut</th>
                  <th className="px-5 py-3 font-medium">Pièces</th>
                  <th className="px-5 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((ligne) => (
                  <LigneDemandeRow
                    key={`${ligne.type}-${ligne.demande.id}`}
                    ligne={ligne}
                    reference={reference}
                    onChange={charger}
                    onDiscussion={setDiscussionOuverte}
                    onErreur={(m) => setErreurs((prev) => (prev.includes(m) ? prev : [...prev, m]))}
                  />
                ))}
              </tbody>
            </table>
          </TableScroll>
        </div>
      )}

      <DiscussionDialog
        demandeId={discussionOuverte}
        titre={ouverte ? titreDiscussion(ouverte) : "Demande"}
        onClose={() => setDiscussionOuverte(null)}
      />
    </div>
  );
}

// useSearchParams exige une frontiere Suspense (build statique de Next).
export default function MesDemandesPage() {
  return (
    <React.Suspense fallback={<SqueletteListe />}>
      <MesDemandes />
    </React.Suspense>
  );
}
