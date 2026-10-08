"""
Devises et conversion (decision du 28/09 : "plusieurs devises avec conversion").

Principes :
- Une devise de REFERENCE (Settings.devise_reference) porte les enveloppes budgetaires, les soldes et le
  seuil d'escalade. Une demande dans une autre devise est CONVERTIE a la soumission.
- Le taux et le montant converti sont FIGES sur la demande : modifier un taux plus tard ne change jamais
  un engagement deja pris (auditabilite : le decideur voit ce qui sera debite, et cela ne bouge plus).
- Le taux applique est le plus recent dont la date d'effet n'est pas posterieure a la date de la depense
  (a la date de soumission pour un achat).
- Les demandes anterieures a cette fonctionnalite n'ont ni devise ni montant converti : elles sont lues
  comme exprimees dans la devise de reference (aucune donnee a migrer).
- Calcul en Decimal, arrondi au centime "commercial" (ROUND_HALF_UP) : pas de derive de flottants.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.taux_change import TauxChange

settings = get_settings()

SYMBOLES = {"EUR": "€"}
CENTIME = Decimal("0.01")


class TauxIntrouvable(ValueError):
    """Aucun taux de change applicable pour cette devise a cette date."""


@dataclass(frozen=True)
class Conversion:
    devise: str
    taux: float
    montant: float
    montant_reference: float
    date_effet: date | None  # None pour la devise de reference (taux implicite de 1)


def devise_reference() -> str:
    return settings.devise_reference.strip().upper()


def normaliser(devise: str | None) -> str:
    """Devise en majuscules ; absente -> devise de reference."""
    return (devise or devise_reference()).strip().upper()


def arrondir(valeur: Decimal) -> float:
    return float(valeur.quantize(CENTIME, rounding=ROUND_HALF_UP))


async def taux_applicable(db: AsyncSession, devise: str, a_la_date: date) -> tuple[Decimal, date] | None:
    resultat = await db.execute(
        select(TauxChange.taux, TauxChange.date_effet)
        .where(TauxChange.devise == devise, TauxChange.date_effet <= a_la_date)
        .order_by(TauxChange.date_effet.desc())
        .limit(1)
    )
    ligne = resultat.first()
    return (Decimal(str(ligne[0])), ligne[1]) if ligne else None


async def convertir(db: AsyncSession, montant: float, devise: str | None, a_la_date: date) -> Conversion:
    """Convertit `montant` (exprime en `devise`) dans la devise de reference a la date donnee."""
    devise = normaliser(devise)
    if devise == devise_reference():
        return Conversion(devise, 1.0, montant, arrondir(Decimal(str(montant))), None)
    applicable = await taux_applicable(db, devise, a_la_date)
    if applicable is None:
        raise TauxIntrouvable(
            f"Aucun taux de change disponible pour {devise} au {a_la_date.strftime('%d/%m/%Y')} : "
            f"contactez la DRH ou le contrôle de gestion pour le renseigner."
        )
    taux, date_effet = applicable
    converti = Decimal(str(montant)) * taux
    return Conversion(devise, float(taux), montant, arrondir(converti), date_effet)


def devise_de(donnees: dict) -> str:
    """Devise d'une demande (les demandes anterieures, sans devise, sont dans la devise de reference)."""
    return normaliser(donnees.get("devise"))


def montant_reference(donnees: dict, cle_montant: str) -> float:
    """Montant d'une demande dans la devise de reference : la valeur figee a la soumission, sinon (donnees
    anterieures a la fonctionnalite) le montant tel quel, qui etait alors toujours dans cette devise."""
    figee = donnees.get(f"{cle_montant}_reference")
    return float(figee if figee is not None else donnees[cle_montant])


def formater(montant: float, devise: str | None) -> str:
    """'1200.0 €' pour l'euro, '1200.0 XAF' sinon."""
    d = normaliser(devise)
    return f"{montant} {SYMBOLES.get(d, d)}"


def libelle_montant(donnees: dict, cle_montant: str) -> str:
    """'800.0 USD (≈ 736.0 €)' si la demande est convertie, '800.0 €' sinon."""
    devise = devise_de(donnees)
    original = formater(float(donnees[cle_montant]), devise)
    if devise == devise_reference():
        return original
    return f"{original} (≈ {formater(montant_reference(donnees, cle_montant), devise_reference())})"
