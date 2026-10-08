"""Schemas de la synthese des notes de frais validees (CDC fonctionnel 3 : transmise a la comptabilite)."""
from datetime import date

from pydantic import BaseModel


class LigneSynthese(BaseModel):
    id: str  # reference du dossier
    valide_le: str
    demandeur_nom: str
    service: str
    categorie: str
    date_depense: date
    description: str
    montant: float
    devise: str
    taux_applique: float
    montant_reference: float
    valide_par: list[str]
    derogation: bool
    nb_pieces: int


class TotalDevise(BaseModel):
    devise: str
    nombre: int
    total: float  # dans la devise d'origine
    total_reference: float  # converti, fige a la soumission


class SyntheseFrais(BaseModel):
    devise_reference: str
    nombre: int
    total_reference: float
    par_devise: list[TotalDevise]
    total_lignes: int  # lignes correspondant aux criteres
    limit: int
    offset: int
    tronque: bool  # vrai si les criteres depassent le plafond de lignes traitees : affiner la periode
    elements: list[LigneSynthese]
