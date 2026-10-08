"""
Schemas generiques de demande (section 4 / 3.4).

Chaque processus (congés, notes de frais, achats) specialise `donnees` avec
son propre schema Pydantic (voir app/schemas/conges.py, notes_frais.py,
achats.py) plutot que de dupliquer l'enveloppe commune ci-dessous.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import StatutDemande, TypeProcessus


class DemandeBase(BaseModel):
    processus: TypeProcessus
    donnees: dict


class DemandeCreate(DemandeBase):
    """TODO: remplacer `dict` par le schema specifique du processus concerne."""
    pass


class DemandeRead(DemandeBase):
    id: uuid.UUID
    demandeur_id: uuid.UUID
    statut_global: StatutDemande
    creee_le: datetime

    class Config:
        from_attributes = True
