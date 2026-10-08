"use client";

import * as React from "react";
import { ApiError, convertirMontant, listerDevises } from "@/lib/api";
import { formaterMontant } from "@/lib/montants";
import type { Conversion, Devise } from "@/types";

/** Devises utilisables et devise de reference (celle des enveloppes budgetaires). "EUR" en attendant la reponse. */
export function useDevises() {
  const [reference, setReference] = React.useState("EUR");
  const [devises, setDevises] = React.useState<Devise[]>([]);
  React.useEffect(() => {
    listerDevises()
      .then((r) => {
        setReference(r.reference);
        setDevises(r.devises);
      })
      .catch(() => setDevises([])); // sans la liste, on reste sur la devise de reference : jamais bloquant
  }, []);
  return { reference, devises };
}

/**
 * Liste des devises. La valeur vide signifie "devise de reference" (aucune conversion). Masquee tant qu'une
 * seule devise existe : inutile d'encombrer le formulaire quand personne n'a defini de taux.
 */
export function ChampDevise({
  id,
  valeur,
  onChange,
  devises,
}: {
  id: string;
  valeur: string;
  onChange: (v: string) => void;
  devises: Devise[];
}) {
  if (devises.length <= 1) return null;
  return (
    <select
      id={id}
      aria-label="Devise"
      value={valeur}
      onChange={(e) => onChange(e.target.value)}
      className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-[13.5px] text-ink"
    >
      {devises.map((d) => (
        <option key={d.code} value={d.code}>
          {d.code}
        </option>
      ))}
    </select>
  );
}

/**
 * Equivalent en devise de reference, au taux qui sera applique (celui en vigueur a la date de la depense),
 * AVANT l'envoi : on ne decouvre pas le montant retenu apres coup. Le taux est ensuite fige sur la demande.
 * Anti-rebond : pas une requete par frappe.
 */
export function ApercuConversion({
  montant,
  devise,
  date,
  reference,
}: {
  montant: string;
  devise: string;
  date?: string;
  reference: string;
}) {
  const [conversion, setConversion] = React.useState<Conversion | null>(null);
  const [erreur, setErreur] = React.useState<string | null>(null);

  React.useEffect(() => {
    const valeur = parseFloat(montant);
    setConversion(null);
    setErreur(null);
    if (!devise || devise === reference || !Number.isFinite(valeur) || valeur <= 0) return;
    let annule = false;
    const minuteur = setTimeout(() => {
      convertirMontant({ montant: valeur, devise, date: date || undefined })
        .then((c) => !annule && setConversion(c))
        .catch((err) => !annule && setErreur(err instanceof ApiError ? err.message : "Conversion impossible."));
    }, 400);
    return () => {
      annule = true;
      clearTimeout(minuteur);
    };
  }, [montant, devise, date, reference]);

  if (erreur) return <p className="text-[12.5px] text-danger">{erreur}</p>;
  if (!conversion) return null;
  return (
    <p className="text-[12.5px] text-ink-dim">
      ≈ {formaterMontant(conversion.montant_reference, conversion.devise_reference)} (1 {conversion.devise} ={" "}
      {conversion.taux} {conversion.devise_reference}
      {conversion.date_effet ? `, taux du ${new Date(conversion.date_effet).toLocaleDateString("fr-FR")}` : ""}). Ce montant
      converti sera figé à l&apos;envoi.
    </p>
  );
}
