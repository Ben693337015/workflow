"""Schemas des enveloppes budgetaires (section 4 / 11 du CDC technique)."""
import uuid

from pydantic import BaseModel, ConfigDict, Field


class EnveloppeBudgetaireCreate(BaseModel):
    service: str = Field(min_length=1, max_length=120)
    exercice: int = Field(ge=2000, le=2100)
    budget_alloue: float = Field(ge=0)


class EnveloppeBudgetaireRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service: str
    exercice: int
    budget_alloue: float
    budget_consomme: float
    solde_disponible: float
