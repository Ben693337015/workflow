"""
Routes de gestion des utilisateurs.

- lister_mon_equipe : consultation, déjà en place (nécessaire à l'écran de
  régularisation).
- creer_utilisateur / modifier_utilisateur / desactiver_utilisateur /
  reactiver_utilisateur : gestion de compte employé par le DRH (écart
  identifié suite à la revue comparative — jusqu'ici, seul le script de
  seed pouvait créer un compte, aucune route applicative n'existait).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import exiger_roles, get_current_user
from app.models.enums import RoleUtilisateur, TypeJetonCompte
from app.models.enums import MotifMouvementConges
from app.models.mouvement_conges import MouvementConges
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.schemas.type_conge import SoldeCongesDefinir, SoldeCongesRead
from app.models.demande import Demande
from app.models.enums import StatutDemande
from app.schemas.user import UtilisateurCreate, UtilisateurModifie, UtilisateurModifier, UtilisateurRead
from app.services import audit, email_gabarit as g, email_service, gestion_demandes, hierarchie, jetons_compte

def _jsonable(valeur):
    """Valeur serialisable pour le journal (enumerations et identifiants -> texte)."""
    if valeur is None or isinstance(valeur, (str, int, float, bool)):
        return valeur
    return str(getattr(valeur, "value", valeur))


router = APIRouter(prefix="/api/v1/utilisateurs", tags=["utilisateurs"])
settings = get_settings()


@router.get("/mon-equipe", response_model=list[UtilisateurRead])
async def lister_mon_equipe(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.MANAGER, RoleUtilisateur.DRH)),
):
    """
    Écart identifié et corrigé (revue du 26/09) : un manager ne se voyait
    jamais lui-même dans cette liste (seuls ses rattachés directs, filtrés
    sur `manager_id == current_user.id`), ce qui l'empêchait de faire une
    régularisation pour sa propre absence via l'écran de régularisation
    (`employe_id` doit être un identifiant présent dans cette liste côté
    frontend). Un manager sans manager au-dessus de lui dans la hiérarchie
    (`manager_id` nul) n'a personne d'autre en mesure de décider pour lui
    par le circuit normal - il doit donc apparaître dans sa propre liste
    pour pouvoir s'auto-régulariser. Aucune restriction côté route de
    régularisation elle-même n'empêchait déjà ce cas (`employe_id` peut
    être n'importe quel utilisateur actif) ; seule cette liste bloquait.
    """
    if current_user.role == RoleUtilisateur.DRH:
        resultat = await db.execute(select(Utilisateur).where(Utilisateur.actif.is_(True)))
    else:
        resultat = await db.execute(
            select(Utilisateur).where(
                (Utilisateur.manager_id == current_user.id) | (Utilisateur.id == current_user.id),
                Utilisateur.actif.is_(True),
            )
        )
    return resultat.scalars().all()


@router.get("/", response_model=list[UtilisateurRead])
async def lister_tous_les_comptes(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    """Liste complète (actifs et inactifs) — réservée au DRH, pour l'écran d'administration."""
    resultat = await db.execute(select(Utilisateur).order_by(Utilisateur.nom_complet))
    return resultat.scalars().all()


@router.post("/", response_model=UtilisateurRead, status_code=status.HTTP_201_CREATED)
async def creer_utilisateur(
    payload: UtilisateurCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    resultat = await db.execute(select(Utilisateur).where(Utilisateur.email == payload.email))
    if resultat.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte existe déjà avec cet e-mail.",
        )

    if payload.manager_id is not None:
        try:
            await hierarchie.valider_manager(db, None, payload.manager_id)
        except hierarchie.ManagerInvalide as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # Ecart corrige (revue du 15/09) : aucun mot de passe defini ici - voir
    # UtilisateurCreate. Le compte reste inactivable a la connexion
    # (mot_de_passe_hash NULL) tant que l'invitation n'a pas ete suivie.
    utilisateur = Utilisateur(
        email=payload.email,
        mot_de_passe_hash=None,
        nom_complet=payload.nom_complet,
        service=payload.service,
        role=payload.role,
        manager_id=payload.manager_id,
    )
    db.add(utilisateur)
    await db.flush()

    jeton = await jetons_compte.generer_jeton_compte(db, utilisateur.id, TypeJetonCompte.INVITATION)
    await audit.consigner(
        db, action="compte_cree", acteur_id=current_user.id, cible_type="utilisateur", cible_id=utilisateur.id,
        details={"email": utilisateur.email, "role": utilisateur.role.value, "service": utilisateur.service},
    )
    await db.commit()
    await db.refresh(utilisateur)

    try:
        await email_service.envoyer_email(
            destinataire=utilisateur.email,
            sujet="👋 Bienvenue — activez votre compte",
            corps_html=_corps_email_invitation(
                payload.role, payload.service, f"{settings.frontend_base_url}/activer-compte/{jeton}"
            ),
        )
    except Exception:
        pass  # section 13.4 : ne doit jamais faire echouer la creation du compte

    return utilisateur


def _corps_email_invitation(role: RoleUtilisateur, service: str, lien_activation: str) -> str:
    return (
        g.paragraphe("Bonjour et bienvenue ! 🎉")
        + g.paragraphe(
            "Votre compte vient d'être créé sur la plateforme d'approbation de workflows : congés, notes de frais "
            "et achats se valident désormais en quelques clics, sans papier ni e-mail perdu."
        )
        + g.carte([("Votre rôle", role.value), ("Votre service", service)])
        + g.boutons(("Activer mon compte", lien_activation, "primaire"))
        + g.note("⏳ Ce lien est valable 7 jours. Vous y choisirez votre mot de passe.")
    )


@router.post("/{utilisateur_id}/renvoyer-invitation", status_code=status.HTTP_200_OK)
async def renvoyer_invitation(
    utilisateur_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    """
    Écart identifié et corrigé (revue du 16/09), suite au test réel de bout
    en bout : si l'e-mail d'invitation initial échoue à l'envoi (Resend
    indisponible, domaine mal configuré...), le jeton en clair est
    définitivement perdu par conception (§9.3, seule l'empreinte est
    stockée) - et jusqu'ici, rien ne permettait de le renvoyer autrement
    qu'en intervenant directement en base.

    Révoque tout jeton d'invitation encore actif pour ce compte (un seul
    lien valide à la fois, §9.3), en émet un nouveau, et tente l'envoi.
    Le lien est toujours renvoyé dans la réponse, que l'e-mail parte ou
    non : contrairement à la création de compte (où l'e-mail est
    secondaire par rapport à la création elle-même), l'envoi EST tout
    l'objet de cette action - son échec doit donc être visible pour la
    DRH, pas absorbé silencieusement.
    """
    utilisateur = await db.get(Utilisateur, utilisateur_id)
    if utilisateur is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")
    if utilisateur.compte_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce compte a déjà été activé — utilisez la réinitialisation de mot de passe plutôt que l'invitation.",
        )
    if not utilisateur.actif:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce compte est désactivé.")

    await jetons_compte.revoquer_jetons_actifs(db, utilisateur.id, TypeJetonCompte.INVITATION)
    jeton = await jetons_compte.generer_jeton_compte(db, utilisateur.id, TypeJetonCompte.INVITATION)
    await audit.consigner(
        db, action="compte_invitation_renvoyee", acteur_id=current_user.id, cible_type="utilisateur",
        cible_id=utilisateur.id, details={"email": utilisateur.email},
    )
    await db.commit()

    lien_activation = f"{settings.frontend_base_url}/activer-compte/{jeton}"
    email_envoye = True
    try:
        await email_service.envoyer_email(
            destinataire=utilisateur.email,
            sujet="👋 Bienvenue — activez votre compte",
            corps_html=_corps_email_invitation(utilisateur.role, utilisateur.service, lien_activation),
        )
    except Exception:
        email_envoye = False

    return {
        "email_envoye": email_envoye,
        "lien_activation": lien_activation,
        "detail": (
            "Invitation renvoyée par e-mail."
            if email_envoye
            else "L'e-mail n'a pas pu être envoyé — communiquez le lien affiché par un autre canal sécurisé."
        ),
    }


@router.patch("/{utilisateur_id}", response_model=UtilisateurModifie)
async def modifier_utilisateur(
    utilisateur_id: uuid.UUID,
    payload: UtilisateurModifier,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    utilisateur = await db.get(Utilisateur, utilisateur_id)
    if utilisateur is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")

    donnees = payload.model_dump(exclude_unset=True)
    ancien_manager_id = utilisateur.manager_id
    manager_change = "manager_id" in donnees and donnees["manager_id"] != ancien_manager_id
    nouveau_manager_id = donnees.get("manager_id")

    # Changement ou attribution de manager (DRH, 05/10) : voir app/services/hierarchie.py.
    paires = []
    if manager_change:
        if nouveau_manager_id is not None:
            try:
                await hierarchie.valider_manager(db, utilisateur_id, nouveau_manager_id)
            except hierarchie.ManagerInvalide as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        elif ancien_manager_id is not None:
            en_attente = await hierarchie.etapes_ouvertes_chez(db, utilisateur_id, ancien_manager_id)
            if en_attente:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"{len(en_attente)} demande(s) de cet employé attendent encore la décision de son manager actuel : "
                        "désignez un remplaçant plutôt que de retirer le manager."
                    ),
                )
        if ancien_manager_id is not None and nouveau_manager_id is not None:
            paires = await hierarchie.reaffecter_etapes(db, utilisateur_id, ancien_manager_id, nouveau_manager_id)

    # Identifiants captures AVANT le commit (les objets sont expires apres) pour la relance ci-dessous.
    a_relancer = [d.id for _e, d in paires if d.statut_global == StatutDemande.EN_COURS]
    nb_reaffectees = len(paires)

    changements = {}
    for champ, valeur in donnees.items():
        avant = getattr(utilisateur, champ)
        if avant != valeur:
            changements[champ] = {"avant": _jsonable(avant), "apres": _jsonable(valeur)}
        setattr(utilisateur, champ, valeur)

    if changements:
        details = {"email": utilisateur.email, "changements": changements}
        if paires:
            details["demandes_reaffectees"] = [str(d.id) for _e, d in paires]
        await audit.consigner(
            db, action="compte_modifie", acteur_id=current_user.id, cible_type="utilisateur",
            cible_id=utilisateur.id, details=details,
        )
    await db.commit()

    # Les demandes en attente de decision recoivent de NOUVEAUX liens, envoyes au nouveau manager : les liens
    # de l'ancien sont revoques (un seul couple actif a la fois). Best effort : un e-mail en echec ne doit pas
    # annuler le changement, la DRH peut relancer manuellement.
    for demande_id in a_relancer:
        try:
            demande = await db.get(Demande, demande_id)
            await gestion_demandes.relancer(db, demande, current_user)
        except Exception:
            await db.rollback()

    await db.refresh(utilisateur)
    return UtilisateurModifie.model_validate(utilisateur).model_copy(update={"demandes_reaffectees": nb_reaffectees})


@router.post("/{utilisateur_id}/desactiver", response_model=UtilisateurRead)
async def desactiver_utilisateur(
    utilisateur_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    utilisateur = await db.get(Utilisateur, utilisateur_id)
    if utilisateur is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")
    utilisateur.actif = False
    await audit.consigner(
        db, action="compte_desactive", acteur_id=current_user.id, cible_type="utilisateur",
        cible_id=utilisateur.id, details={"email": utilisateur.email},
    )
    await db.commit()
    await db.refresh(utilisateur)
    return utilisateur


@router.post("/{utilisateur_id}/reactiver", response_model=UtilisateurRead)
async def reactiver_utilisateur(
    utilisateur_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    utilisateur = await db.get(Utilisateur, utilisateur_id)
    if utilisateur is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")
    utilisateur.actif = True
    await audit.consigner(
        db, action="compte_reactive", acteur_id=current_user.id, cible_type="utilisateur",
        cible_id=utilisateur.id, details={"email": utilisateur.email},
    )
    await db.commit()
    await db.refresh(utilisateur)
    return utilisateur


# --- Solde de congés par employé et par type (écart identifié, revue du
# 17/09) : jusqu'ici, rien ne permettait à la DRH de définir le solde d'un
# employé - le seul moyen était une intervention manuelle en base (seed).
# Sans cette route, aucune demande de congé ne pouvait jamais être
# approuvée sur un déploiement réel (le verrou RH traite un solde absent
# comme 0 jour disponible, §11). ---------------------------------------


@router.get("/{utilisateur_id}/soldes-conges", response_model=list[SoldeCongesRead])
async def lister_soldes_conges(
    utilisateur_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """La DRH peut consulter le solde de n'importe qui ; un employé, seulement le sien."""
    if current_user.role != RoleUtilisateur.DRH and current_user.id != utilisateur_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé.")
    resultat = await db.execute(select(SoldeConges).where(SoldeConges.utilisateur_id == utilisateur_id))
    return resultat.scalars().all()


@router.put("/{utilisateur_id}/soldes-conges", response_model=SoldeCongesRead)
async def definir_solde_conges(
    utilisateur_id: uuid.UUID,
    payload: SoldeCongesDefinir,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.DRH)),
):
    """
    Définit (crée ou met à jour) le nombre de jours acquis d'un employé
    pour un type de congé et un exercice donnés — l'acte RH explicite exigé
    par le CDC (§11.1.1 : "Solde initial DRH, depuis son tableau de bord").

    Modifier un solde existant préserve les jours déjà consommés
    (`jours_pris`) : seul l'écart entre l'ancien et le nouveau nombre de
    jours acquis est répercuté sur le solde disponible, plutôt que
    d'écraser purement et simplement le solde restant.
    """
    utilisateur = await db.get(Utilisateur, utilisateur_id)
    if utilisateur is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")
    type_conge = await db.get(TypeConge, payload.type_conge_id)
    if type_conge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Type de congé introuvable.")

    resultat = await db.execute(
        select(SoldeConges).where(
            SoldeConges.utilisateur_id == utilisateur_id,
            SoldeConges.type_conge_id == payload.type_conge_id,
            SoldeConges.exercice == payload.exercice,
        )
    )
    solde = resultat.scalar_one_or_none()
    jours_acquis_avant = float(solde.jours_acquis) if solde is not None else None
    if solde is None:
        solde = SoldeConges(
            utilisateur_id=utilisateur_id,
            type_conge_id=payload.type_conge_id,
            exercice=payload.exercice,
            jours_acquis=payload.jours_acquis,
            jours_pris=0,
            jours_reserves=0,
            solde_jours=payload.jours_acquis,
        )
        db.add(solde)
        if payload.jours_acquis:
            # Tout changement du solde passe par un mouvement (CDC 11.1.1, R17).
            db.add(
                MouvementConges(
                    utilisateur_id=utilisateur_id, type_conge_id=payload.type_conge_id,
                    exercice=payload.exercice, demande_id=None, delta=payload.jours_acquis,
                    motif=MotifMouvementConges.SOLDE_INITIAL,
                )
            )
    else:
        ecart = payload.jours_acquis - float(solde.jours_acquis)
        solde.jours_acquis = payload.jours_acquis
        solde.solde_jours = float(solde.solde_jours) + ecart
        if ecart:
            db.add(
                MouvementConges(
                    utilisateur_id=utilisateur_id, type_conge_id=payload.type_conge_id,
                    exercice=payload.exercice, demande_id=None, delta=ecart,
                    motif=MotifMouvementConges.AJUSTEMENT_MANUEL,
                )
            )

    await audit.consigner(
        db, action="solde_conges_defini", acteur_id=current_user.id, cible_type="utilisateur",
        cible_id=utilisateur_id,
        details={
            "type_conge_id": str(payload.type_conge_id), "exercice": payload.exercice,
            "jours_acquis_avant": jours_acquis_avant, "jours_acquis_apres": float(payload.jours_acquis),
        },
    )
    await db.commit()
    await db.refresh(solde)
    return solde
