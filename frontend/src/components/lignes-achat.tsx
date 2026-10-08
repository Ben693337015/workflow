"use client";

import * as React from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/form";
import { formaterMontant } from "@/lib/montants";
import type { LigneAchat } from "@/types";

const LIGNE_VIDE: LigneAchat = { description: "", montant_ht: 0, taux_tva: 20 };

/**
 * Detail par ligne d'un achat (CDC technique 4.1 : "calculs de taxes differencies par ligne").
 * Chaque ligne est saisie HT ; le TTC et la TVA de chaque ligne, ainsi que les totaux, sont
 * calcules ici pour un apercu immediat - le calcul qui fait foi reste celui du backend a la
 * soumission (app/services/facturation.py), identique a celui-ci.
 */
export function LignesAchat({
  lignes,
  onChange,
  devise,
}: {
  lignes: LigneAchat[];
  onChange: (lignes: LigneAchat[]) => void;
  devise: string;
}) {
  function modifier(index: number, champ: keyof LigneAchat, valeur: string) {
    const copie = lignes.map((l, i) =>
      i === index ? { ...l, [champ]: champ === "description" ? valeur : parseFloat(valeur) || 0 } : l
    );
    onChange(copie);
  }

  function ajouter() {
    onChange([...lignes, { ...LIGNE_VIDE }]);
  }

  function retirer(index: number) {
    onChange(lignes.filter((_, i) => i !== index));
  }

  const totalHt = lignes.reduce((s, l) => s + (l.montant_ht || 0), 0);
  const totalTtc = lignes.reduce((s, l) => s + (l.montant_ht || 0) * (1 + (l.taux_tva || 0) / 100), 0);

  return (
    <div className="flex flex-col gap-3">
      {lignes.map((ligne, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto_auto_auto] items-end gap-2 rounded-lg bg-canvas p-3">
          <div className="flex flex-col gap-1">
            {i === 0 && <Label htmlFor={`ligne-description-${i}`}>Description</Label>}
            <Input
              id={`ligne-description-${i}`}
              value={ligne.description}
              onChange={(e) => modifier(i, "description", e.target.value)}
              placeholder="Ex. Licence logicielle"
            />
          </div>
          <div className="flex flex-col gap-1">
            {i === 0 && <Label htmlFor={`ligne-ht-${i}`}>Montant HT</Label>}
            <Input
              id={`ligne-ht-${i}`}
              type="number"
              step="0.01"
              min="0.01"
              className="w-28"
              value={ligne.montant_ht || ""}
              onChange={(e) => modifier(i, "montant_ht", e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            {i === 0 && <Label htmlFor={`ligne-tva-${i}`}>TVA (%)</Label>}
            <Input
              id={`ligne-tva-${i}`}
              type="number"
              step="0.1"
              min="0"
              max="100"
              className="w-20"
              value={ligne.taux_tva}
              onChange={(e) => modifier(i, "taux_tva", e.target.value)}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => retirer(i)}
            disabled={lignes.length === 1}
            aria-label={`Retirer la ligne ${i + 1}`}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}

      <Button type="button" variant="outline" onClick={ajouter} className="w-fit gap-1.5">
        <Plus className="h-4 w-4" />
        Ajouter une ligne
      </Button>

      <p className="text-[13px] text-ink-dim">
        Total HT : <strong className="text-ink">{formaterMontant(totalHt, devise)}</strong> — Total TTC :{" "}
        <strong className="text-ink">{formaterMontant(totalTtc, devise)}</strong>
      </p>
    </div>
  );
}
