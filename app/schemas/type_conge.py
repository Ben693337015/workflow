"""Schemas des types de congé (écart identifié : type de congé structuré)."""
import uuid

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.config import get_settings


class TypeCongeCreate(BaseModel):
    code: str
    nom: str
    taux_acquisition_jours_mois: float = 0

    @field_validator("code")
    @classmethod
    def code_non_vide(cls, valeur: str) -> str:
        valeur = valeur.strip().lower().replace(" ", "_")
        if not valeur:
            raise ValueError("Le code est obligatoire.")
        return valeur


class TypeCongeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    nom: str
    taux_acquisition_jours_mois: float
    actif: bool


class SoldeCongesDefinir(BaseModel):
    """
    Écart identifié (revue du 17/09) : jusqu'ici, rien ne permettait à la
    DRH de définir le solde d'un employé pour un type de congé donné - la
    seule façon d'en créer un était une intervention manuelle en base
    (script de seed ou de démonstration). Sans cette route, aucun employé
    ne pouvait jamais soumettre une demande sur un déploiement réel : le
    verrou RH (§11) traite un solde absent comme 0 jour disponible.
    """

    type_conge_id: uuid.UUID
    exercice: int
    jours_acquis: float

    @field_validator("jours_acquis")
    @classmethod
    def jours_acquis_positifs(cls, valeur: float) -> float:
        if valeur < 0:
            raise ValueError("Le nombre de jours acquis ne peut pas être négatif.")
        # R4 (decision D2b) : jours entiers uniquement, pas de demi-journee. Le reglage
        # `conges_unite_jour_entier` etait defini mais lu nulle part.
        if get_settings().conges_unite_jour_entier and float(valeur) != int(valeur):
            raise ValueError("Le nombre de jours acquis doit être un nombre entier (pas de demi-journée).")
        return valeur


class SoldeCongesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type_conge_id: uuid.UUID
    exercice: int
    jours_acquis: float
    jours_pris: float
    jours_reserves: float = 0
    solde_jours: float
