"""
Schéma du formulaire de demande de congés (section 3 - tableau des cas
d'usage, et section 6 - intégrité de la saisie).

Écart identifié corrigé : le type de congé était une chaîne libre, sans lien
avec une entité structurée (nécessaire pour appliquer un taux d'acquisition
et un solde par type, décision déjà confirmée). Il référence maintenant
un type_conge_id.
"""
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class DemandeCongesCreate(BaseModel):
    type_conge_id: uuid.UUID
    date_debut: date
    date_fin: date
    # Ecart identifié (revue du 16/09) : aucun moyen pour le demandeur d'ajouter
    # du contexte libre (ex. "pose d'un jour à cheval sur le pont du 1er mai").
    # Optionnel : ne doit pas devenir une justification obligatoire, qui
    # relève du justificatif (pièce jointe) et non d'un commentaire.
    commentaire: str | None = None

    @field_validator("commentaire")
    @classmethod
    def commentaire_normalise(cls, valeur: str | None) -> str | None:
        if valeur is None:
            return None
        valeur = valeur.strip()
        return valeur or None

    @model_validator(mode="after")
    def dates_coherentes(self) -> "DemandeCongesCreate":
        if self.date_fin < self.date_debut:
            raise ValueError(
                "La date de fin doit etre posterieure ou egale a la date de debut."
            )
        return self


class DemandeCongesModifier(BaseModel):
    """Modification d'une demande encore en attente (écart identifié : absent avant cette étape)."""

    type_conge_id: uuid.UUID | None = None
    date_debut: date | None = None
    date_fin: date | None = None
    commentaire: str | None = None

    @model_validator(mode="after")
    def dates_coherentes_si_les_deux_fournies(self) -> "DemandeCongesModifier":
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise ValueError(
                "La date de fin doit etre posterieure ou egale a la date de debut."
            )
        return self


class RegularisationCongesCreate(BaseModel):
    """
    Demande créée et immédiatement décidée par un manager/DRH au nom d'un
    employé (écart identifié : absence constatée après coup, non justifiée
    à la saisie par l'employé lui-même).
    """

    employe_id: uuid.UUID
    type_conge_id: uuid.UUID
    date_debut: date
    date_fin: date
    action: str  # "approuver" ou "refuser"
    commentaire: str | None = None

    @field_validator("action")
    @classmethod
    def action_valide(cls, valeur: str) -> str:
        if valeur not in {"approuver", "refuser"}:
            raise ValueError("L'action doit être 'approuver' ou 'refuser'.")
        return valeur

    @model_validator(mode="after")
    def dates_coherentes(self) -> "RegularisationCongesCreate":
        if self.date_fin < self.date_debut:
            raise ValueError(
                "La date de fin doit etre posterieure ou egale a la date de debut."
            )
        return self


class DemandeCongesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type_conge_id: str
    date_debut: date
    date_fin: date
    nombre_jours: int
    statut_global: str
