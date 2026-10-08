"""
Calcul des montants d'un bon de commande (CDC technique §4.1 : "exécuter les calculs financiers
(Total HT, TVA par taux, Total TTC)", et écart constaté : "pas de lignes ; un seul taux (20 %)
appliqué à un montant supposé TTC").

Deux modes, tous deux exposés via TotauxBonDeCommande pour un rendu PDF unique :
- `totaux_depuis_lignes` : une demande d'achat détaillée en lignes (description, montant HT, taux de
  TVA propre à chacune) - le mode attendu par le CDC. Chaque ligne est calculée individuellement, puis
  regroupée par taux ("TVA par taux") pour les sous-totaux.
- `totaux_depuis_montant_global` : mode antérieur (une demande sans lignes, un seul montant TTC et un
  taux global unique) - conservé pour ne jamais faire échouer la génération d'un bon de commande créé
  avant cette extension (aucune ligne alors enregistrée).

Calcul en Decimal, arrondi commercial (ROUND_HALF_UP) : même principe que app/services/devises.py,
pour ne jamais laisser une dérive de flottants s'introduire dans un montant contractuel.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTIME = Decimal("0.01")


def _d(valeur) -> Decimal:
    return Decimal(str(valeur))


def _arrondir(valeur: Decimal) -> float:
    return float(valeur.quantize(CENTIME, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class LigneCalculee:
    description: str
    montant_ht: float
    taux_tva: float
    montant_tva: float
    montant_ttc: float


@dataclass(frozen=True)
class SousTotalTaux:
    taux_tva: float
    montant_ht: float
    montant_tva: float
    montant_ttc: float


@dataclass(frozen=True)
class TotauxBonDeCommande:
    detail_par_ligne: bool  # False en mode legacy (ligne implicite unique, retrocompatibilite)
    lignes: list[LigneCalculee]
    par_taux: list[SousTotalTaux]
    total_ht: float
    total_tva: float
    total_ttc: float


def calculer_lignes(lignes_brutes: list[dict]) -> list[LigneCalculee]:
    """Calcule le montant de TVA et le TTC de chaque ligne (montant HT et taux de TVA saisis)."""
    resultat = []
    for ligne in lignes_brutes:
        ht = _d(ligne["montant_ht"])
        taux = _d(ligne["taux_tva"])
        tva = ht * taux / Decimal(100)
        resultat.append(
            LigneCalculee(
                description=str(ligne["description"]),
                montant_ht=_arrondir(ht),
                taux_tva=float(taux),
                montant_tva=_arrondir(tva),
                montant_ttc=_arrondir(ht + tva),
            )
        )
    return resultat


def somme_ttc(lignes_brutes: list[dict]) -> float:
    """Total TTC de la demande, deduit des lignes : source unique de verite pour le budget engage."""
    return _arrondir(sum((_d(l["montant_ht"]) * (Decimal(1) + _d(l["taux_tva"]) / Decimal(100))) for l in lignes_brutes))


def totaux_depuis_lignes(lignes_brutes: list[dict]) -> TotauxBonDeCommande:
    """Detail par ligne, sous-totaux par taux (CDC technique 4.1 : "TVA par taux"), totaux generaux."""
    lignes = calculer_lignes(lignes_brutes)
    par_taux_brut: dict[float, tuple[Decimal, Decimal]] = {}
    for ligne in lignes:
        ht_cumule, tva_cumulee = par_taux_brut.get(ligne.taux_tva, (Decimal(0), Decimal(0)))
        par_taux_brut[ligne.taux_tva] = (ht_cumule + _d(ligne.montant_ht), tva_cumulee + _d(ligne.montant_tva))
    par_taux = [
        SousTotalTaux(taux_tva=taux, montant_ht=_arrondir(ht), montant_tva=_arrondir(tva), montant_ttc=_arrondir(ht + tva))
        for taux, (ht, tva) in sorted(par_taux_brut.items())
    ]
    total_ht = sum(_d(l.montant_ht) for l in lignes)
    total_tva = sum(_d(l.montant_tva) for l in lignes)
    return TotauxBonDeCommande(
        detail_par_ligne=True,
        lignes=lignes,
        par_taux=par_taux,
        total_ht=_arrondir(total_ht),
        total_tva=_arrondir(total_tva),
        total_ttc=_arrondir(total_ht + total_tva),
    )


def totaux_depuis_montant_global(montant_ttc: float, taux_tva_pct: float) -> TotauxBonDeCommande:
    """Mode legacy : une demande sans lignes detaillees, un seul taux applique globalement (avant le 28/09)."""
    ttc = _d(montant_ttc)
    taux = _d(taux_tva_pct)
    ht = ttc / (Decimal(1) + taux / Decimal(100))
    tva = ttc - ht
    sous_total = SousTotalTaux(taux_tva=float(taux), montant_ht=_arrondir(ht), montant_tva=_arrondir(tva), montant_ttc=_arrondir(ttc))
    return TotauxBonDeCommande(
        detail_par_ligne=False,
        lignes=[],
        par_taux=[sous_total],
        total_ht=_arrondir(ht),
        total_tva=_arrondir(tva),
        total_ttc=_arrondir(ttc),
    )
