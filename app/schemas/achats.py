"""
Schemas du processus "Validation d'achats et contrats" (section 3, tableau
des cas d'usage).
"""
from app.schemas.pieces_jointes import PieceJointeRead
from pydantic import BaseModel, Field, field_validator, model_validator


class LigneAchat(BaseModel):
    """
    Ligne detaillee d'un achat (CDC technique 4.1 : "calculs de taxes differencies par ligne").
    Le montant est saisi HT ; le TTC et la TVA de la ligne sont calcules (app/services/facturation.py),
    jamais saisis directement, pour qu'ils ne puissent pas etre incoherents avec le taux indique.
    """
    description: str = Field(min_length=1, max_length=200)
    montant_ht: float = Field(gt=0)
    taux_tva: float = Field(ge=0, le=100, description="Taux de TVA de cette ligne, en pourcentage (ex. 20 pour 20 %).")

    @field_validator("montant_ht")
    @classmethod
    def arrondir(cls, valeur: float) -> float:
        return round(valeur, 2)


class DemandeAchatCreate(BaseModel):
    tiers: str = Field(min_length=1, max_length=200, description="Nom du fournisseur/tiers.")
    objet: str = Field(min_length=1, max_length=500)
    # Optionnel des que `lignes` est fourni : le budget engage est alors deduit du total TTC des
    # lignes (source unique de verite, jamais deux montants qui pourraient diverger). Reste
    # obligatoire en l'absence de lignes, pour la retrocompatibilite avec les demandes anterieures
    # a cette extension (CDC technique 4.1 : detail par ligne, ajoute le 28/09).
    budget_engage: float | None = Field(default=None, gt=0)
    # Detail par ligne (description, montant HT, taux de TVA propre a chacune). Ecart corrige le
    # 28/09 : jusqu'ici un seul taux global (20 %) etait applique a un montant suppose TTC, sans
    # jamais de ventilation par ligne ni par taux, contrairement a l'exigence du CDC technique.
    lignes: list[LigneAchat] | None = Field(default=None, min_length=1, max_length=50)
    # Devise du montant engage (code ISO 4217). Absente : devise de reference. Convertie a la
    # soumission au taux du jour, fige sur la demande (decision du 28/09).
    devise: str | None = Field(default=None, min_length=3, max_length=3)
    # Ecart n°4 (section 4.4 du CDC fonctionnel), meme mecanisme que pour
    # les notes de frais - voir app/schemas/notes_frais.py.
    derogation_motivee: bool = False
    motif_derogation: str | None = Field(default=None, max_length=1000)

    @field_validator("devise")
    @classmethod
    def devise_en_majuscules(cls, valeur: str | None) -> str | None:
        return valeur.strip().upper() if valeur else None

    @field_validator("budget_engage")
    @classmethod
    def arrondir_budget(cls, valeur: float | None) -> float | None:
        return round(valeur, 2) if valeur is not None else None

    @model_validator(mode="after")
    def budget_ou_lignes(self) -> "DemandeAchatCreate":
        if not self.lignes and self.budget_engage is None:
            raise ValueError("Indiquez le budget engagé, ou le détail des lignes de la commande.")
        return self

    @model_validator(mode="after")
    def motif_obligatoire_si_derogation(self) -> "DemandeAchatCreate":
        if self.derogation_motivee and not (self.motif_derogation and self.motif_derogation.strip()):
            raise ValueError(
                "Un motif est obligatoire lorsque la case « demande de dérogation motivée » est cochée."
            )
        return self


class DemandeAchatRead(BaseModel):
    id: str
    statut_global: str
    donnees: dict
    creee_le: str | None = None
    pieces_jointes: list[PieceJointeRead] = []


class SoumissionAchatResponse(BaseModel):
    id: str
    statut_global: str
    premiere_etape_id: str
    derogation: bool = False
    devise: str = ""
    taux_applique: float = 1.0
    budget_engage_reference: float = 0.0
