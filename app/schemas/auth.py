"""Schemas d'authentification (section 5)."""
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.enums import RoleUtilisateur


class LoginRequest(BaseModel):
    email: EmailStr
    mot_de_passe: str


class RefreshRequest(BaseModel):
    refresh_token: str


class MotDePasseOublieRequest(BaseModel):
    """Ecart corrige (revue du 15/09) : mecanisme exige par le CDC (section 5), absent avant cette date."""

    email: EmailStr


class DefinirMotDePasseRequest(BaseModel):
    """
    Utilisée à la fois pour l'invitation initiale (compte créé par le DRH
    sans mot de passe, section 5) et pour la réinitialisation après oubli -
    même jeton opaque, même contrainte de robustesse (voir
    UtilisateurCreate.longueur_minimale, reprise ici à l'identique).
    """

    jeton: str
    mot_de_passe: str

    @field_validator("mot_de_passe")
    @classmethod
    def longueur_minimale(cls, valeur: str) -> str:
        if len(valeur) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")
        return valeur


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UtilisateurRead(BaseModel):
    """Nécessaire pour que le frontend sache qui est connecté et son rôle."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    nom_complet: str
    service: str
    role: RoleUtilisateur
