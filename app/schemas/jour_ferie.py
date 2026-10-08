"""Schemas des jours fériés (écart identifié suite à la revue comparative)."""
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict


class JourFerieCreate(BaseModel):
    nom: str
    date: date
    recurrent: bool = True


class JourFerieRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    date: date
    recurrent: bool
