"""
Schémas utilisateur : lecture du profil (GET /auth/me) et gestion de compte
par le DRH (écart identifié — création/modification/désactivation d'un
compte employé, absente avant cette étape).
"""
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.enums import RoleUtilisateur


class UtilisateurRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    nom_complet: str
    service: str
    role: RoleUtilisateur
    manager_id: uuid.UUID | None = None
    actif: bool = True
    compte_active: bool = True


class UtilisateurModifie(UtilisateurRead):
    """Reponse de PATCH : le profil + le nombre de demandes en cours transmises a un nouveau manager."""

    demandes_reaffectees: int = 0


class UtilisateurCreate(BaseModel):
    """
    Ecart corrige (revue du 15/09) : ne porte plus de mot_de_passe. Le DRH
    définit l'identité et le rôle ; l'employé choisit lui-même son mot de
    passe via le lien d'invitation envoyé par e-mail (section 5, même
    principe que les liens de décision, section 9) - le DRH ne doit jamais
    connaître ni transmettre le mot de passe de qui que ce soit.
    """

    email: EmailStr
    nom_complet: str
    service: str
    role: RoleUtilisateur
    manager_id: uuid.UUID | None = None

    @field_validator("nom_complet", "service")
    @classmethod
    def non_vide(cls, valeur: str) -> str:
        valeur = valeur.strip()
        if not valeur:
            raise ValueError("Ce champ est obligatoire.")
        return valeur


class UtilisateurModifier(BaseModel):
    nom_complet: str | None = None
    service: str | None = None
    role: RoleUtilisateur | None = None
    manager_id: uuid.UUID | None = None
    actif: bool | None = None
