"""
Schemas du processus "Notes de frais" (section 3, tableau des cas d'usage
/ section 7, routage conditionnel sur le montant).

Simplification assumee par rapport au stub d'origine : pas de champ
`devise` (multi-devises) - le montant est traite en euros uniquement, seule
devise mentionnee dans le seuil de routage du CDC
(Settings.notes_frais_seuil_direction_financiere). Le champ `categorie`
du stub d'origine est conserve (texte libre, ex. "Transport",
"Restauration") : n'affecte ni le routage ni le suivi budgetaire, mais
utile pour la lecture humaine de la demande.
"""
from datetime import UTC, date, datetime

from app.schemas.pieces_jointes import PieceJointeRead
from pydantic import BaseModel, Field, field_validator, model_validator


class NoteFraisCreate(BaseModel):
    montant: float = Field(gt=0, description="Montant TTC de la depense, en euros.")
    categorie: str = Field(min_length=1, max_length=120)
    date_depense: date
    description: str = Field(min_length=1, max_length=500)
    # Devise de la depense (code ISO 4217). Absente : devise de reference. Convertie a la soumission
    # (taux en vigueur a la date de la depense, fige sur la demande).
    devise: str | None = Field(default=None, min_length=3, max_length=3)
    # Ecart n°4 (section 4.4 du CDC fonctionnel) : le demandeur peut cocher
    # une case de derogation motivee, detournant le circuit standard vers
    # un arbitrage exceptionnel (notes de frais : Direction financiere seule)
    # - meme sans depassement budgetaire detecte automatiquement.
    derogation_motivee: bool = False
    motif_derogation: str | None = Field(default=None, max_length=1000)

    @field_validator("date_depense")
    @classmethod
    def date_non_future(cls, valeur: date) -> date:
        # CDC 2.1 (integrite de la saisie) : "coherence chronologique des
        # dates". Une depense ne peut pas dater du futur : elle ne peut pas
        # encore avoir ete engagee (aucun controle n'existait auparavant).
        if valeur > datetime.now(UTC).date():
            raise ValueError("La date de la dépense ne peut pas être dans le futur.")
        return valeur

    @field_validator("devise")
    @classmethod
    def devise_en_majuscules(cls, valeur: str | None) -> str | None:
        return valeur.strip().upper() if valeur else None

    @field_validator("montant")
    @classmethod
    def arrondir_montant(cls, valeur: float) -> float:
        return round(valeur, 2)

    @model_validator(mode="after")
    def motif_obligatoire_si_derogation(self) -> "NoteFraisCreate":
        if self.derogation_motivee and not (self.motif_derogation and self.motif_derogation.strip()):
            raise ValueError(
                "Un motif est obligatoire lorsque la case « demande de dérogation motivée » est cochée."
            )
        return self


class NoteFraisRead(BaseModel):
    id: str
    statut_global: str
    donnees: dict
    creee_le: str | None = None
    pieces_jointes: list[PieceJointeRead] = []


class SoumissionNotesFraisResponse(BaseModel):
    id: str
    statut_global: str
    premiere_etape_id: str
    derogation: bool = False
    # Conversion figee a la soumission (devise de la depense -> devise de reference).
    devise: str = ""
    taux_applique: float = 1.0
    montant_reference: float = 0.0
