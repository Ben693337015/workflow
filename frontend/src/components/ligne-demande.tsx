"use client";

import { CalendarDays, Download, Receipt, ShoppingCart, type LucideIcon } from "lucide-react";
import { ActionsDemande } from "@/components/actions-demande";
import { PiecesJointes } from "@/components/pieces-jointes";
import {
  ApiError,
  annulerDemandeAchat,
  annulerDemandeConges,
  annulerNoteDeFrais,
  relancerDemandeAchat,
  relancerNoteDeFrais,
  relancerNotificationConges,
  telechargerBonDeCommande,
  telechargerContratAchat,
  telechargerFicheConfirmation,
} from "@/lib/api";
import { statutDe, TYPES_DEMANDE, type LigneDemande, type TypeDemande } from "@/lib/demandes";
import { formaterAvecEquivalent } from "@/lib/montants";
import { enregistrerFichier } from "@/lib/telechargement";

export const ICONES_TYPE: Record<TypeDemande, LucideIcon> = {
  conges: CalendarDays,
  notes_frais: Receipt,
  achats: ShoppingCart,
};

/**
 * Pastille de type : neutre (bordure, fond du canevas) et munie d'une icone, pour ne jamais se confondre avec la
 * pastille de STATUT, elle, coloree. Le meme couple icone/libelle sert d'onglet de filtre et de menu.
 */
export function PastilleType({ type }: { type: TypeDemande }) {
  const Icone = ICONES_TYPE[type];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line bg-canvas px-2 py-1 text-[12px] font-medium text-ink-dim">
      <Icone className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden="true" />
      {TYPES_DEMANDE[type].label}
    </span>
  );
}

const ouverte = (statut: string) => statut === "en_cours" || statut === "complement_demande";

/** Titre de la boite de discussion : rappelle de quelle demande il s'agit. */
export function titreDiscussion(ligne: LigneDemande): string {
  if (ligne.type === "conges") return `Congé du ${ligne.demande.donnees.date_debut} au ${ligne.demande.donnees.date_fin}`;
  if (ligne.type === "notes_frais")
    return `Note de frais « ${ligne.demande.donnees.categorie} » du ${ligne.demande.donnees.date_depense}`;
  return `Demande d'achat — ${ligne.demande.donnees.tiers}`;
}

const LIEN = "text-[12.5px] text-accent-text hover:underline";

export function LigneDemandeRow({
  ligne,
  reference,
  onChange,
  onDiscussion,
  onErreur,
}: {
  ligne: LigneDemande;
  reference: string;
  onChange: () => void;
  onDiscussion: (id: string) => void;
  onErreur: (message: string) => void;
}) {
  const statut = statutDe(ligne);
  const id = ligne.demande.id;
  const statutGlobal = ligne.demande.statut_global;

  async function telecharger(action: () => Promise<Blob>, nom: string, messageDefaut: string) {
    try {
      enregistrerFichier(await action(), nom);
    } catch (err) {
      onErreur(err instanceof ApiError ? err.message : messageDefaut);
    }
  }

  let titre: string;
  let detail: React.ReactNode;
  let pieces: React.ReactNode;
  let actions: React.ReactNode;

  if (ligne.type === "conges") {
    const d = ligne.demande;
    titre = `${d.donnees.date_debut} — ${d.donnees.date_fin}`;
    detail = d.donnees.commentaire || "—";
    pieces = (
      <PiecesJointes demandeId={id} pieces={d.pieces_jointes ?? []} peutAjouter={ouverte(statutGlobal)} onAjoutee={onChange} />
    );
    actions = (
      <>
        <ActionsDemande
          demandeId={id}
          peutAnnuler={ouverte(statutGlobal)}
          peutRelancer={statutGlobal === "en_cours"}
          annuler={annulerDemandeConges}
          relancer={relancerNotificationConges}
          onChange={onChange}
        />
        {statutGlobal === "terminee" && (
          <button
            onClick={() => telecharger(() => telechargerFicheConfirmation(id), `fiche-confirmation-${id}.pdf`, "Impossible de télécharger la fiche.")}
            className={`flex items-center gap-1 ${LIEN}`}
          >
            <Download className="h-3.5 w-3.5" />
            Fiche
          </button>
        )}
      </>
    );
  } else if (ligne.type === "notes_frais") {
    const d = ligne.demande;
    titre = d.donnees.categorie;
    detail = `${d.donnees.date_depense} · ${formaterAvecEquivalent(
      d.donnees.montant,
      d.donnees.devise ?? reference,
      d.donnees.montant_reference,
      reference
    )}`;
    pieces = (
      <PiecesJointes demandeId={id} pieces={d.pieces_jointes ?? []} peutAjouter={ouverte(statutGlobal)} onAjoutee={onChange} />
    );
    actions = (
      <ActionsDemande
        demandeId={id}
        peutAnnuler={ouverte(statutGlobal)}
        peutRelancer={statutGlobal === "en_cours"}
        annuler={annulerNoteDeFrais}
        relancer={relancerNoteDeFrais}
        onChange={onChange}
      />
    );
  } else {
    const d = ligne.demande;
    titre = d.donnees.tiers;
    detail = (
      <>
        {formaterAvecEquivalent(d.donnees.budget_engage, d.donnees.devise ?? reference, d.donnees.budget_engage_reference, reference)}
        {d.donnees.lignes && d.donnees.lignes.length > 0 && (
          <span
            className="ml-1.5 text-[11.5px] text-ink-faint"
            title={d.donnees.lignes.map((l) => `${l.description} — ${l.montant_ht} HT (TVA ${l.taux_tva} %)`).join("\n")}
          >
            ({d.donnees.lignes.length} ligne{d.donnees.lignes.length > 1 ? "s" : ""})
          </span>
        )}
      </>
    );
    pieces = (
      <div className="flex flex-wrap gap-3">
        <button onClick={() => telecharger(() => telechargerContratAchat(id), "contrat", "Téléchargement impossible.")} className={`flex items-center gap-1 ${LIEN}`}>
          <Download className="h-3.5 w-3.5" />
          Contrat
        </button>
        {statutGlobal === "terminee" && d.donnees.numero_bc && (
          <button
            onClick={() => telecharger(() => telechargerBonDeCommande(id), `${d.donnees.numero_bc}.pdf`, "Téléchargement impossible.")}
            className={`flex items-center gap-1 ${LIEN}`}
          >
            <Download className="h-3.5 w-3.5" />
            Bon de commande
          </button>
        )}
      </div>
    );
    actions = (
      <ActionsDemande
        demandeId={id}
        peutAnnuler={ouverte(statutGlobal)}
        peutRelancer={statutGlobal === "en_cours"}
        annuler={annulerDemandeAchat}
        relancer={relancerDemandeAchat}
        onChange={onChange}
      />
    );
  }

  return (
    <tr className="border-b border-line last:border-0 hover:bg-canvas">
      <td data-label="Type" className="cell-fixe px-5 py-3.5">
        <PastilleType type={ligne.type} />
      </td>
      <td data-label="Demande" className="px-5 py-3.5">
        {/* Largeur bornee : un fournisseur ou une categorie tres long ne doit jamais elargir tout le tableau. */}
        <div className="max-w-[16rem]">
          <div className="line-clamp-2 font-medium text-ink [overflow-wrap:anywhere]" title={titre}>{titre}</div>
          <div className="mt-0.5 truncate text-[12.5px] text-ink-dim">{detail}</div>
        </div>
      </td>
      <td data-label="Statut" className="px-5 py-3.5">
        <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-medium ${statut.className}`}>
          {statut.label}
        </span>
      </td>
      <td data-label="Pièces" className="px-5 py-3.5">{pieces}</td>
      <td data-label="Actions" className="px-5 py-3.5">
        <div className="flex flex-col items-start gap-2">
          {actions}
          {statutGlobal === "complement_demande" && (
            <button onClick={() => onDiscussion(id)} className={LIEN}>
              Discussion
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
