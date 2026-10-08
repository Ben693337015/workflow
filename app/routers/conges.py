"""
Routes du processus "Demande de congés".

Flux de soumission conforme à la section 13.2 du CDC technique (étapes 1 à
10) : verrou RH synchrone -> création transactionnelle de la demande et de
la première étape -> jetons de décision -> notification e-mail -> webhook ->
journal d'audit.

Étendu suite à la revue comparative avec des plateformes de référence
(écarts identifiés, tous marqués ci-dessous) : jours fériés déductibles,
type de congé structuré, modification et annulation d'une demande en
attente, régularisation par un manager/DRH au nom d'un employé.
"""
import uuid
from datetime import UTC, date, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import exiger_roles, get_current_user
from app.models.demande import Demande
from app.models.enums import (
    MotifMouvementConges,
    EvenementWebhook,
    RoleEtape,
    RoleUtilisateur,
    StatutDemande,
    StatutEtape,
    TypeProcessus,
)
from app.models.etape_workflow import EtapeWorkflow
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.schemas.conges import (
    DemandeCongesCreate,
    DemandeCongesModifier,
    RegularisationCongesCreate,
)
from app.services import audit, decision_tokens, documents, email_gabarit as g, email_service, gestion_demandes, pieces, routing_engine, webhooks
from app.services.extensions import verrou_rh

router = APIRouter(prefix="/api/v1/conges", tags=["conges"])
settings = get_settings()


async def _verifier_type_conge_actif(db: AsyncSession, type_conge_id: uuid.UUID) -> TypeConge:
    type_conge = await db.get(TypeConge, type_conge_id)
    if type_conge is None or not type_conge.actif:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Type de congé inconnu ou inactif.",
        )
    return type_conge


@router.post("/", status_code=status.HTTP_201_CREATED)
async def soumettre_demande_conges(
    payload: DemandeCongesCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    await _verifier_type_conge_actif(db, payload.type_conge_id)

    # --- Etape 4 (section 13.2) : verification synchrone AVANT toute creation. ---
    ok, nombre_jours, solde_disponible = await verrou_rh.solde_suffisant(
        db, current_user, payload.type_conge_id, payload.date_debut, payload.date_fin
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Solde de congés insuffisant : {nombre_jours} jour(s) décompté(s) demandé(s) "
                f"(jours fériés déjà exclus) pour {solde_disponible} jour(s) disponible(s)."
            ),
        )

    # --- Etape 5 : creation transactionnelle demande + premiere etape. ---
    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=current_user.id,
        initiee_par_id=current_user.id,
        donnees=payload.model_dump(mode="json"),
        statut_global=StatutDemande.EN_COURS,
    )
    db.add(demande)
    await db.flush()

    # --- Reservation du solde (R17, CDC 11.1.2) : sous verrou de ligne, dans la MEME transaction que la
    # creation de la demande. Le controle ci-dessus est un refus rapide sans verrou ; celui-ci fait foi : si
    # une autre soumission a consomme le solde entre-temps, on annule tout et on refuse. ---
    reservation_faite, solde_reel = await verrou_rh.reserver_solde(
        db, current_user.id, payload.type_conge_id, payload.date_debut.year, nombre_jours, demande.id
    )
    if not reservation_faite:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Solde de congés insuffisant : {nombre_jours} jour(s) décompté(s) demandé(s) "
                f"pour {solde_reel} jour(s) disponible(s) (une autre demande vient de réserver des jours)."
            ),
        )

    # Ecart identifie et corrige (revue du 15/09) : un employe sans manager
    # rattache (nouvel arrivant pas encore affecte, DRH/direction en haut de
    # la hierarchie...) faisait planter la route en 500 (ValueError non
    # rattrapee) au lieu d'un rejet propre - reproduit et confirme avant
    # correction.
    try:
        etape = await routing_engine.determiner_premiere_etape(db, demande, current_user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucun manager n'est rattaché à votre compte : contactez la DRH avant de soumettre une demande.",
        ) from exc
    db.add(etape)
    await db.flush()

    # --- Etape 6 : jetons de decision (un par action possible, section 9.3). ---
    jeton_approuver = await decision_tokens.generer_jeton_decision(
        db, etape.id, "approuver", etape.approbateur_attendu_id
    )
    jeton_refuser = await decision_tokens.generer_jeton_decision(
        db, etape.id, "refuser", etape.approbateur_attendu_id
    )

    await db.commit()
    await db.refresh(demande)
    await db.refresh(etape)

    # --- Etape 7 : notification e-mail au manager (best-effort). ---
    manager = await db.get(Utilisateur, etape.approbateur_attendu_id)
    try:
        # Ecart identifié (revue du 16/09) : le commentaire libre du
        # demandeur (nouveau champ, DemandeCongesCreate.commentaire) était
        # capturé et stocké mais jamais transmis au manager - il fallait
        # rouvrir la demande pour le lire. Échappé (comme dans la fiche de
        # confirmation, §12) puisque c'est du texte libre saisi par l'utilisateur.
        bloc_commentaire = g.encart(payload.commentaire, "Message du demandeur", emoji="💬") if payload.commentaire else ""
        await email_service.envoyer_email(
            destinataire=manager.email if manager else "",
            sujet=f"📅 Nouvelle demande de congés à valider — {current_user.nom_complet}",
            corps_html=(
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"<strong>{escape(current_user.nom_complet)}</strong> ({escape(current_user.service)}) "
                    "vous a adressé une demande de congés et attend votre décision. "
                    "Quelques secondes suffisent pour lui répondre 🙌"
                )
                + g.carte([
                    ("Période", f"du {payload.date_debut.strftime('%d/%m/%Y')} au {payload.date_fin.strftime('%d/%m/%Y')}"),
                    ("Durée décomptée", f"{nombre_jours} jour(s) (jours fériés déjà exclus)"),
                ])
                + bloc_commentaire
                + g.boutons(
                    ("Approuver", f"{settings.frontend_base_url}/decisions/{jeton_approuver}", "primaire"),
                    ("Refuser", f"{settings.frontend_base_url}/decisions/{jeton_refuser}", "danger"),
                )
                + g.note("🔒 Ces liens sont personnels et à usage unique : vous confirmerez votre décision après connexion.")
            ),
        )
    except Exception:
        pass  # section 13.4 : ne doit jamais faire echouer la soumission

    # --- Etape 8 : webhook sortant si un abonnement existe. ---
    await webhooks.notifier_evenement(
        db, demande.id, TypeProcessus.CONGES, EvenementWebhook.DEMANDE_SOUMISE
    )

    # --- Etape 9 : journal d'audit. ---
    await audit.consigner(
        db,
        action="demande_soumise",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"processus": "conges", "nombre_jours": nombre_jours},
    )
    await db.commit()

    # --- Etape 10 : reponse HTTP 201 avec l'identifiant de la demande. ---
    return {
        "id": str(demande.id),
        "statut_global": demande.statut_global.value,
        "nombre_jours": nombre_jours,
        "premiere_etape_id": str(etape.id),
    }


@router.get("/")
async def lister_mes_demandes(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """
    Liste les demandes de congés du demandeur connecté, les plus récentes
    d'abord (nécessaire pour l'écran "Mes demandes" du frontend — absent du
    périmètre initial, qui ne couvrait que la consultation par identifiant).
    """
    resultat = await db.execute(
        select(Demande)
        .where(Demande.demandeur_id == current_user.id, Demande.processus == TypeProcessus.CONGES)
        .order_by(Demande.creee_le.desc())
    )
    demandes = resultat.scalars().all()
    pieces_par_id = await pieces.pieces_par_demande(db, [d.id for d in demandes])
    return [
        {
            "id": str(d.id),
            "statut_global": d.statut_global.value,
            "donnees": d.donnees,
            "creee_le": d.creee_le.isoformat(),
            "pieces_jointes": [p.model_dump() for p in pieces_par_id.get(d.id, [])],
        }
        for d in demandes
    ]


@router.get("/agenda-equipe")
async def lister_agenda_equipe(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.MANAGER, RoleUtilisateur.DRH)),
):
    """
    Mise à jour de l'agenda de l'équipe (CDC fonctionnel, section 3 :
    livrable attendu en fin de circuit, avec la fiche de confirmation).

    Calculé à la volée à partir des demandes déjà approuvées plutôt que
    tenu comme un agenda persistant séparé : la donnée source (Demande)
    est déjà la source de vérité, un second stockage la dupliquerait sans
    apporter de garantie supplémentaire.

    IMPORTANT (ordre des routes) : cette route DOIT rester déclarée avant
    `GET /{demande_id}` ci-dessous - sinon FastAPI tente de convertir
    "agenda-equipe" en UUID et renvoie 422 au lieu d'atteindre cette route.
    """
    if current_user.role == RoleUtilisateur.DRH:
        filtre = select(Utilisateur.id).where(Utilisateur.actif.is_(True))
    else:
        filtre = select(Utilisateur.id).where(
            Utilisateur.manager_id == current_user.id, Utilisateur.actif.is_(True)
        )
    ids_equipe = (await db.execute(filtre)).scalars().all()

    resultat = await db.execute(
        select(Demande, Utilisateur)
        .join(Utilisateur, Utilisateur.id == Demande.demandeur_id)
        .where(
            Demande.processus == TypeProcessus.CONGES,
            Demande.statut_global == StatutDemande.TERMINEE,
            Demande.demandeur_id.in_(ids_equipe),
        )
    )
    evenements = [
        {
            "demande_id": str(d.id),
            "employe_id": str(u.id),
            "employe_nom": u.nom_complet,
            "date_debut": d.donnees["date_debut"],
            "date_fin": d.donnees["date_fin"],
        }
        for d, u in resultat.all()
    ]
    # Tri en Python plutôt qu'en SQL : extraire une clé de tri portable
    # depuis une colonne JSON générique (SQLite/PostgreSQL) demanderait une
    # syntaxe spécifique au dialecte, alors que le nombre de lignes attendu
    # (absences approuvées d'une équipe) reste largement trivial à trier ici.
    evenements.sort(key=lambda e: e["date_debut"])
    return evenements


@router.get("/{demande_id}")
async def consulter_demande_conges(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """
    Retourne l'etat de la demande pour le tableau de bord (section 12).

    Acces restreint (correction R19 : cette route etait auparavant ouverte a
    quiconque connaissait l'identifiant) : le demandeur, son manager, la DRH,
    ou un approbateur attendu sur l'une des etapes de la demande. Un refus est
    renvoye en 404 pour les autres, afin de ne pas reveler l'existence d'un
    dossier a un utilisateur qui n'y a pas droit.
    """
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.CONGES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")

    autorise = current_user.id == demande.demandeur_id or current_user.role == RoleUtilisateur.DRH
    if not autorise:
        demandeur = await db.get(Utilisateur, demande.demandeur_id)
        autorise = demandeur is not None and demandeur.manager_id == current_user.id
    if not autorise:
        resultat = await db.execute(
            select(EtapeWorkflow.id).where(
                EtapeWorkflow.demande_id == demande.id,
                EtapeWorkflow.approbateur_attendu_id == current_user.id,
            )
        )
        autorise = resultat.first() is not None
    if not autorise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")

    return {
        "id": str(demande.id),
        "statut_global": demande.statut_global.value,
        "donnees": demande.donnees,
    }


@router.get("/{demande_id}/fiche-confirmation")
async def telecharger_fiche_confirmation(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """
    Fiche de confirmation d'absence (CDC fonctionnel, section 3 : livrable
    attendu en fin de circuit congés). Génération à la demande - voir la
    note dans app/services/documents.py sur le choix de ne pas persister
    le fichier tant que le stockage réel (NubiS3) n'est pas raccordé.

    Accès : le demandeur lui-même, son manager, ou la DRH.
    """
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.CONGES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    if demande.statut_global != StatutDemande.TERMINEE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La fiche de confirmation n'est disponible que pour une demande approuvée.",
        )

    employe = await db.get(Utilisateur, demande.demandeur_id)
    autorise = (
        current_user.id == demande.demandeur_id
        or (employe is not None and employe.manager_id == current_user.id)
        or current_user.role == RoleUtilisateur.DRH
    )
    if not autorise:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vous n'avez pas accès à ce document.")

    type_conge = await db.get(TypeConge, uuid.UUID(demande.donnees["type_conge_id"]))
    date_debut = date.fromisoformat(demande.donnees["date_debut"])
    date_fin = date.fromisoformat(demande.donnees["date_fin"])
    nombre_jours = await verrou_rh.calculer_duree_deductible(db, date_debut, date_fin)

    # Ecart identifié corrigé : la fiche ne mentionnait pas le manager ayant
    # réellement approuvé la demande. Récupération de l'étape approuvée
    # correspondante (role APPROBATEUR, statut APPROUVE) pour signer le
    # document en son nom et dater l'approbation.
    resultat_etape = await db.execute(
        select(EtapeWorkflow).where(
            EtapeWorkflow.demande_id == demande.id,
            EtapeWorkflow.role == RoleEtape.APPROBATEUR,
            EtapeWorkflow.statut == StatutEtape.APPROUVE,
        )
    )
    etape_approuvee = resultat_etape.scalar_one_or_none()
    manager = (
        await db.get(Utilisateur, etape_approuvee.approbateur_attendu_id) if etape_approuvee else None
    )
    date_approbation = etape_approuvee.date_reponse if etape_approuvee else None

    pdf = documents.generer_fiche_confirmation_absence(
        demande, employe, type_conge, nombre_jours, manager=manager, date_approbation=date_approbation
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="fiche-confirmation-{demande.id}.pdf"'},
    )


@router.patch("/{demande_id}")
async def modifier_demande_conges(
    demande_id: uuid.UUID,
    payload: DemandeCongesModifier,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """
    Modifie une demande de congés tant qu'elle n'a pas encore été décidée
    (écart identifié : absent avant cette étape). Seul le demandeur peut
    modifier sa propre demande, et uniquement si elle est encore EN_COURS.
    """
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.CONGES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    if demande.demandeur_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cette demande ne vous appartient pas.")
    if demande.statut_global != StatutDemande.EN_COURS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seule une demande encore en cours peut être modifiée.",
        )

    nouvelles_donnees = dict(demande.donnees)
    if payload.type_conge_id is not None:
        await _verifier_type_conge_actif(db, payload.type_conge_id)
        nouvelles_donnees["type_conge_id"] = str(payload.type_conge_id)
    if payload.date_debut is not None:
        nouvelles_donnees["date_debut"] = payload.date_debut.isoformat()
    if payload.date_fin is not None:
        nouvelles_donnees["date_fin"] = payload.date_fin.isoformat()
    if payload.commentaire is not None:
        nouvelles_donnees["commentaire"] = payload.commentaire.strip() or None

    date_debut = date.fromisoformat(nouvelles_donnees["date_debut"])
    date_fin = date.fromisoformat(nouvelles_donnees["date_fin"])
    if date_fin < date_debut:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin doit être postérieure ou égale à la date de début.",
        )

    # R17 : la demande detient deja une reservation (ancienne periode). On la libere, on verifie et on reserve
    # la nouvelle periode sous verrou, dans une seule transaction : en cas de solde insuffisant, tout est annule
    # et l'ancienne reservation reste intacte.
    nombre_jours = await verrou_rh.calculer_duree_deductible(db, date_debut, date_fin)
    await verrou_rh.liberer_reservation(db, demande, MotifMouvementConges.LIBERATION_MODIFICATION)
    reservation_faite, solde_disponible = await verrou_rh.reserver_solde(
        db, current_user.id, uuid.UUID(nouvelles_donnees["type_conge_id"]), date_debut.year, nombre_jours, demande.id
    )
    if not reservation_faite:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Solde de congés insuffisant pour la nouvelle période : {nombre_jours} jour(s) "
                f"demandé(s) pour {solde_disponible} jour(s) disponible(s)."
            ),
        )

    demande.donnees = nouvelles_donnees
    await audit.consigner(
        db,
        action="demande_modifiee",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"nouvelles_donnees": nouvelles_donnees},
    )
    await db.commit()
    await db.refresh(demande)

    return {"id": str(demande.id), "donnees": demande.donnees, "nombre_jours": nombre_jours}


@router.post("/{demande_id}/annuler")
async def annuler_demande_conges(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Annule une demande de congés encore en cours. Logique partagée avec notes de frais et achats
    (écart corrigé le 28/09 : cette action n'existait que pour les congés) : app/services/gestion_demandes.py."""
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.CONGES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return await gestion_demandes.annuler(db, demande, current_user)


@router.post("/{demande_id}/relancer")
async def relancer_notification_decision(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Relance manuelle (à distinguer des rappels automatiques à échéance fixe, §2.4,
    app/services/rappels.py). Logique partagée : app/services/gestion_demandes.py."""
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.CONGES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return await gestion_demandes.relancer(db, demande, current_user)


@router.post("/regularisation", status_code=status.HTTP_201_CREATED)
async def regulariser_demande_conges(
    payload: RegularisationCongesCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(exiger_roles(RoleUtilisateur.MANAGER, RoleUtilisateur.DRH)),
):
    """
    Crée et décide immédiatement une demande de congés au nom d'un employé
    (écart identifié : régularisation d'une absence constatée après coup,
    sans passer par le circuit normal de décision par e-mail).
    """
    employe = await db.get(Utilisateur, payload.employe_id)
    if employe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employé introuvable.")

    await _verifier_type_conge_actif(db, payload.type_conge_id)

    nombre_jours = await verrou_rh.calculer_duree_deductible(db, payload.date_debut, payload.date_fin)

    if payload.action == "refuser" and not (payload.commentaire and payload.commentaire.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un commentaire est obligatoire en cas de refus.",
        )

    if payload.action == "approuver":
        ok, _, solde_disponible = await verrou_rh.solde_suffisant(
            db, employe, payload.type_conge_id, payload.date_debut, payload.date_fin
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Solde de congés insuffisant pour régulariser : {nombre_jours} jour(s) "
                    f"pour {solde_disponible} jour(s) disponible(s)."
                ),
            )

    donnees = {
        "type_conge_id": str(payload.type_conge_id),
        "date_debut": payload.date_debut.isoformat(),
        "date_fin": payload.date_fin.isoformat(),
    }
    statut_global = StatutDemande.TERMINEE if payload.action == "approuver" else StatutDemande.REFUSEE

    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=employe.id,
        initiee_par_id=current_user.id,
        donnees=donnees,
        statut_global=statut_global,
    )
    db.add(demande)
    await db.flush()

    etape = EtapeWorkflow(
        demande_id=demande.id,
        niveau=1,
        role=RoleEtape.APPROBATEUR,
        approbateur_attendu_id=current_user.id,
        statut=StatutEtape.APPROUVE if payload.action == "approuver" else StatutEtape.REFUSE,
        commentaire=payload.commentaire,
        date_reponse=datetime.now(UTC),
    )
    db.add(etape)
    await db.flush()

    if payload.action == "approuver":
        # Meme chemin que le circuit normal (R17) : reservation sous verrou, puis confirmation immediate.
        reservation_faite, solde_reel = await verrou_rh.reserver_solde(
            db, employe.id, payload.type_conge_id, payload.date_debut.year, nombre_jours, demande.id
        )
        if not reservation_faite:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Solde de congés insuffisant pour régulariser : {nombre_jours} jour(s) "
                    f"pour {solde_reel} jour(s) disponible(s)."
                ),
            )
        await verrou_rh.confirmer_reservation(db, demande)

    await db.commit()
    await db.refresh(demande)

    evenement = (
        EvenementWebhook.CIRCUIT_TERMINE if payload.action == "approuver" else EvenementWebhook.ETAPE_REFUSEE
    )
    await webhooks.notifier_evenement(db, demande.id, TypeProcessus.CONGES, evenement)

    # Ecart identifié et corrige (revue du 15/09) : une régularisation est
    # décidée au nom de l'employé, sans passer par son propre clic - a
    # fortiori il doit en être informé, sinon il peut ignorer qu'une absence
    # a été actée (ou refusée) en son nom. Meme exigence et meme motif que
    # pour le circuit normal (CDC fonctionnel : notifications d'avancement).
    try:
        periode = f"du {payload.date_debut.strftime('%d/%m/%Y')} au {payload.date_fin.strftime('%d/%m/%Y')}"
        if payload.action == "approuver":
            sujet = f"✅ Une régularisation de congé {periode} a été enregistrée pour vous"
            corps = (
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"{escape(current_user.nom_complet)} a régularisé et approuvé en votre nom une absence "
                    f"{periode} ({nombre_jours} jour(s) décompté(s)). Tout est en ordre de votre côté 🌿"
                )
            )
        else:
            sujet = f"❌ Une demande de régularisation de congé {periode} a été refusée"
            corps = (
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"La demande de régularisation de congé {periode} vous concernant a été refusée par "
                    f"{escape(current_user.nom_complet)}."
                )
                + g.encart(payload.commentaire or "", "Motif communiqué", "refus", "💬")
            )
        await email_service.envoyer_email(destinataire=employe.email, sujet=sujet, corps_html=corps)
    except Exception:
        pass  # section 13.4 : ne doit jamais faire echouer la regularisation

    await audit.consigner(
        db,
        action="demande_regularisee",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={"employe_id": str(employe.id), "action": payload.action, "commentaire": payload.commentaire},
    )
    await db.commit()

    return {
        "id": str(demande.id),
        "statut_global": demande.statut_global.value,
        "nombre_jours": nombre_jours,
    }
