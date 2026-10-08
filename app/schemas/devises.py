"""Schemas des devises et taux de change (decision du 28/09 : plusieurs devises avec conversion)."""
import re
from datetime import date

from pydantic import BaseModel, Field, field_validator


class TauxChangeDefinir(BaseModel):
    devise: str
    taux: float = Field(gt=0, lt=1_000_000_000, description="Unites de la devise de reference pour 1 unite de `devise`.")
    date_effet: date

    @field_validator("devise")
    @classmethod
    def code_iso(cls, valeur: str) -> str:
        valeur = valeur.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", valeur):
            raise ValueError("La devise doit être un code ISO 4217 de 3 lettres (ex. USD, XAF).")
        return valeur


class TauxChangeRead(BaseModel):
    id: str
    devise: str
    taux: float
    date_effet: date


class DeviseRead(BaseModel):
    code: str
    taux: float  # unites de la devise de reference pour 1 unite ; 1 pour la devise de reference
    date_effet: date | None  # None pour la devise de reference


class DevisesRead(BaseModel):
    reference: str
    devises: list[DeviseRead]


class ConversionRead(BaseModel):
    devise: str
    devise_reference: str
    taux: float
    montant: float
    montant_reference: float
    date_effet: date | None
