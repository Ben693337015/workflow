"""Schemas de consultation du journal d'audit (CDC fonctionnel 2.4 : tracabilite)."""
from pydantic import BaseModel


class AuditEntree(BaseModel):
    id: str
    action: str
    libelle: str
    acteur_id: str | None
    acteur_nom: str
    cible_type: str
    cible_id: str | None
    details: dict
    horodate_le: str


class AuditPage(BaseModel):
    total: int
    limit: int
    offset: int
    elements: list[AuditEntree]


class ActionAudit(BaseModel):
    action: str
    libelle: str


class HistoriqueEntree(BaseModel):
    """Ligne de la chronologie d'un dossier : qui a fait quoi, et quand."""
    horodate_le: str
    action: str
    libelle: str
    acteur_nom: str
    detail: str | None = None
