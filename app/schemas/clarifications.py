"""Schemas de l'espace de discussion parallele (ecart n°5, section 4.5 du CDC)."""
from pydantic import BaseModel, Field


class SuspensionCreate(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="Motif de la demande de précisions.")


class MessageCreate(BaseModel):
    contenu: str = Field(min_length=1, max_length=2000)


class MessageRead(BaseModel):
    id: str
    auteur_id: str
    auteur_nom: str
    contenu: str
    cree_le: str
    fichier_nom: str | None = None
