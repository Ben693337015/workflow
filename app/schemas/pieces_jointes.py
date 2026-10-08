"""Schemas des pieces jointes d'une demande (recu, justificatif, contrat, complements)."""
from pydantic import BaseModel


class PieceJointeRead(BaseModel):
    id: str
    nom: str
    categorie: str
