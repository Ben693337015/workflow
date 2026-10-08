"""
Route de décision par lien e-mail en un clic (section 9 / 13.3 du CDC technique).

Flux complet (section 13.3, étapes 11 à 19) :
verification du jeton (§9.3) -> verification de session (option B, §9.1) ->
mise a jour de l'etape + consommation du jeton -> reevaluation du routage ->
effets de bord (documents, notification, webhook) -> journal d'audit.

Portee actuelle : seul le processus congés est cable au-dela de la
verification du jeton (un seul niveau -> pas de reevaluation de routage
necessaire). Les notes de frais et les achats, avec leurs niveaux
supplementaires, restent a implementer (moteur de routage section 7).
"""
import asyncio
import base64
import logging
from html import escape
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.models.demande import Demande
from app.models.enums import (
    EvenementWebhook,
    MotifMouvementConges,
    RoleEtape,
    RoleUtilisateur,
    StatutDemande,
    StatutEtape,
    TypeProcessus,
)
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.schemas.decisions import ApercuDecision, BudgetApercu, DecisionRequest, DecisionResponse
from app.services import (
    pieces_email,
    audit,
    decision_tokens,
    devises,
    email_gabarit as g,
    email_service,
    numerotation_bc,
    pieces,
    signature,
    routing_engine,
    stockage_fichiers,
    synthese_frais,
    webhooks,
)
from app.services.extensions import suivi_budgetaire, verrou_rh

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])
settings = get_settings()
logger = logging.getLogger(__name__)

ACTIONS_VALIDES = {"approuver", "refuser", "signer"}


def _lignes_resume_escalade(demande: Demande, nom_demandeur: str) -> list[tuple[str, str]]:
    """Fiche récapitulative jointe à l'e-mail d'escalade : l'approbateur suivant voit l'essentiel sans ouvrir la demande."""
    d = demande.donnees
    lignes = [("Demandeur", nom_demandeur)]
    if demande.processus == TypeProcessus.NOTES_FRAIS:
        lignes += [
            ("Montant", devises.libelle_montant(d, "montant")),
            ("Catégorie", d.get("categorie", "")),
            ("Date de la dépense", d.get("date_depense", "")),
            ("Description", d.get("description", "")),
        ]
    elif demande.processus == TypeProcessus.ACHATS:
        lignes += [
            ("Fournisseur / tiers", d.get("tiers", "")),
            ("Montant", devises.libelle_montant(d, "budget_engage")),
            ("Objet de la dépense", d.get("objet", "")),
        ]
    return lignes


async def _notifier_drh(
    db: AsyncSession,
    demande: Demande,
    action: str,
    demandeur: "Utilisateur | None",
    date_debut: date,
    date_fin: date,
    nombre_jours: int,
) -> None:
    """
    Notifie automatiquement le service RH (role DRH) de l'issue d'une
    decision de conge - CDC fonctionnel, section 3 : "Validation par le
    superieur hierarchique direct, puis notification automatique au
    service RH." Le circuit reste a un seul niveau (le manager decide
    seul) ; la DRH est destinataire en copie, sans pouvoir de blocage
    (role "Destinataire en copie", section 8 du CDC technique).

    Ecart identifie et corrige (revue du 15/09) : le corps ne mentionnait
    que l'identifiant technique (UUID) de la demande - la DRH devait aller
    chercher elle-meme de qui et de quelles dates il s'agissait. Inclut
    desormais le nom du demandeur et les dates du conge, sur l'approbation
    comme sur le refus (auparavant calculees uniquement a l'approbation).

    Best-effort (section 13.4) : ne doit jamais faire echouer la decision.
    """
    nom_demandeur = demandeur.nom_complet if demandeur else "un employé"
    periode = f"du {date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}"
    resultat = await db.execute(
        select(Utilisateur).where(Utilisateur.role == RoleUtilisateur.DRH, Utilisateur.actif.is_(True))
    )
    for drh in resultat.scalars().all():
        try:
            if action == "approuver":
                sujet = f"✅ Congé approuvé — {nom_demandeur} — pour information"
                corps = (
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        f"Bonne nouvelle côté équipe : la demande de congé de <strong>{escape(nom_demandeur)}</strong> {periode} "
                        f"({nombre_jours} jour(s) décompté(s)) a été approuvée par le manager 🌴 Le planning de l'équipe est à jour."
                    )
                    + g.note("Ce message est transmis à titre d'information : aucune action n'est attendue de votre part.")
                )
            else:
                sujet = f"❌ Congé refusé — {nom_demandeur} — pour information"
                corps = (
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        f"La demande de congé de <strong>{escape(nom_demandeur)}</strong> {periode} "
                        f"({nombre_jours} jour(s) décompté(s)) a été refusée par le manager. Le demandeur en a été informé avec le motif."
                    )
                    + g.note("Ce message est transmis à titre d'information : aucune action n'est attendue de votre part.")
                )
            await email_service.envoyer_email(destinataire=drh.email, sujet=sujet, corps_html=corps)
        except Exception:
            pass  # section 13.4 : ne doit jamais faire echouer la decision elle-meme


async def _notifier_demandeur(
    db: AsyncSession,
    demande: Demande,
    action: str,
    commentaire: "str | None",
    decideur: "Utilisateur | None",
    date_debut: date,
    date_fin: date,
    nombre_jours: int,
) -> None:
    """
    Notifie le demandeur de l'issue de sa propre demande.

    Ecart identifie et corrige (revue du 15/09) : le CDC fonctionnel exige
    explicitement que "le Demandeur... recoit les notifications d'avancement
    (approbation finale ou rejet motive)". Jusqu'ici, seule la DRH etait
    notifiee (_notifier_drh, ci-dessus) ; le demandeur lui-meme ne recevait
    jamais d'e-mail sur l'issue de sa propre demande, alors meme que c'est
    lui le principal concerne. Le motif de refus (commentaire, obligatoire
    a la decision) est repris integralement : c'est le "rejet motive" exige.

    Deuxieme ecart corrige dans la meme revue : le corps ne precisait ni les
    dates du conge concerne (un employe avec plusieurs demandes en cours ne
    pouvait pas savoir laquelle venait d'etre decidee), ni le nom du manager
    ayant statue.

    Best-effort (section 13.4) : ne doit jamais faire echouer la decision.
    """
    demandeur = await db.get(Utilisateur, demande.demandeur_id)
    if demandeur is None:
        return
    nom_decideur = decideur.nom_complet if decideur else "votre manager"
    periode = f"du {date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}"
    try:
        if action == "approuver":
            sujet = f"🎉 Votre demande de congé {periode} a été approuvée"
            corps = (
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"Bonne nouvelle : votre demande de congé {periode} ({nombre_jours} jour(s) décompté(s)) "
                    f"a été approuvée par <strong>{escape(nom_decideur)}</strong>. Profitez bien de ce moment de repos 🌴"
                )
                + g.carte([("Période", periode.replace("du ", "Du ", 1)), ("Durée décomptée", f"{nombre_jours} jour(s)"),
                           ("Approuvé par", nom_decideur)])
                + g.note("📄 Votre fiche de confirmation d'absence est disponible dans « Mes demandes ».")
            )
        else:
            sujet = f"❌ Votre demande de congé {periode} a été refusée"
            corps = (
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"Nous sommes désolés : votre demande de congé {periode} a été refusée par "
                    f"<strong>{escape(nom_decideur)}</strong>."
                )
                + g.encart(commentaire or "", "Motif communiqué", "refus", "💬")
                + g.note("Vous pouvez en discuter avec votre manager et déposer une nouvelle demande sur d'autres dates.")
            )
        await email_service.envoyer_email(destinataire=demandeur.email, sujet=sujet, corps_html=corps)
    except Exception:
        pass  # section 13.4 : ne doit jamais faire echouer la decision elle-meme



@router.get("/{jeton}", response_model=ApercuDecision)
async def previsualiser_decision(jeton: str, db: AsyncSession = Depends(get_db)):
    """
    Lecture seule, jamais de consommation du jeton (voir la docstring de
    `verifier_et_consommer_jeton_decision` : verifier et consommer sont deux
    actes distincts ici). Permet au frontend de savoir a l'avance si le
    formulaire de decision doit demander une signature (role Signataire),
    une justification d'acceptation (etape.est_derogation), et d'afficher
    un resume adapte au processus concerne - sans quoi la page de decision
    devrait deviner ou tout demander systematiquement.
    """
    try:
        jeton_ligne = await decision_tokens.verifier_et_consommer_jeton_decision(db, jeton)
    except decision_tokens.JetonDecisionInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton de décision invalide ou expiré.",
        ) from exc

    etape = await db.get(EtapeWorkflow, jeton_ligne.etape_workflow_id)
    if etape is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Étape de workflow introuvable.")
    demande = await db.get(Demande, etape.demande_id)
    demandeur = await db.get(Utilisateur, demande.demandeur_id) if demande else None

    budget = await suivi_budgetaire.resume_budgetaire_demande(db, demande, demandeur) if demande else None

    return ApercuDecision(
        action=jeton_ligne.action_autorisee,
        processus=demande.processus.value if demande else "",
        est_derogation=etape.est_derogation,
        demande_id=str(demande.id) if demande else "",
        statut_demande=demande.statut_global.value if demande else "",
        demandeur_nom=demandeur.nom_complet if demandeur else "Demandeur inconnu",
        resume=demande.donnees if demande else {},
        budget=BudgetApercu(**budget) if budget else None,
        pieces_jointes=(await pieces.pieces_par_demande(db, [demande.id])).get(demande.id, []) if demande else [],
    )


async def _appliquer_effets_finaux(db: AsyncSession, demande: Demande, etape_suivante, action: str) -> None:
    """
    Effets de la finalisation d'un circuit sur les ressources (solde de congés, budget, numéro de bon
    de commande), écrits DANS LA MÊME TRANSACTION que la décision elle-même (correction R18, CDC 13.3
    étape 14).

    Avant : la décision était validée par un premier commit, puis le débit était fait après. Un
    incident entre les deux laissait une demande approuvée sans débit du solde ni du budget.
    Maintenant : l'étape, la demande, le jeton consommé, le débit et le numéro sont validés ensemble
    par un seul commit - ou pas du tout.

    Ne fait rien tant que le circuit continue (escalade vers une étape suivante) : aucune décision
    définitive n'a encore été prise sur la ressource.
    """
    if etape_suivante is not None:
        return
    approuve = action in ("approuver", "signer")

    if demande.processus == TypeProcessus.CONGES:
        if approuve:
            # Les jours réservés à la soumission deviennent des jours pris.
            await verrou_rh.confirmer_reservation(db, demande)
        else:
            await verrou_rh.liberer_reservation(db, demande, MotifMouvementConges.LIBERATION_REFUS)
        return

    if not approuve:
        return

    demandeur = await db.get(Utilisateur, demande.demandeur_id)
    if demandeur is None:
        return

    if demande.processus == TypeProcessus.NOTES_FRAIS:
        # Montant CONVERTI, figé à la soumission ; exercice = année de la dépense, pas de la décision.
        exercice = date.fromisoformat(demande.donnees["date_depense"]).year
        montant = devises.montant_reference(demande.donnees, "montant")
        await suivi_budgetaire.consommer_budget(db, demandeur.service, exercice, montant)
    elif demande.processus == TypeProcessus.ACHATS:
        exercice = demande.creee_le.year if demande.creee_le else datetime.now(UTC).year
        budget_engage = devises.montant_reference(demande.donnees, "budget_engage")
        await suivi_budgetaire.consommer_budget(db, demandeur.service, exercice, budget_engage)
        # Numéro de bon de commande : compteur verrouillé (R21), persisté dans `donnees` pour que le
        # même numéro soit renvoyé à chaque téléchargement du bon.
        numero = await numerotation_bc.attribuer_numero(db, demande, exercice)
        demande.donnees = {**demande.donnees, "numero_bc": numero}


@router.post("/{jeton}", response_model=DecisionResponse)
async def decider(
    jeton: str,
    payload: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur | None = Depends(get_current_user_optional),
):
    # --- Etape 13 (section 13.3) : verification et consommation du jeton. ---
    # Ecart corrige (revue du 15/09) : le jeton est desormais opaque et
    # verifie/consomme contre la table jetons_decision (section 9.3), et
    # non plus decode localement (itsdangerous) sans aucun aller-retour en
    # base au moment de la verification.
    try:
        jeton_ligne = await decision_tokens.verifier_et_consommer_jeton_decision(db, jeton)
    except decision_tokens.JetonDecisionDejaUtilise as exc:
        # Distinct des autres invalidités (401) : un jeton deja consomme
        # signale un conflit avec une decision deja prise, pas un jeton qui
        # n'a jamais ete valide.
        await audit.consigner(
            db,
            action="tentative_jeton_invalide",
            acteur_id=current_user.id if current_user else None,
            cible_type="jeton_decision",
            cible_id=None,
            details={"motif": str(exc)},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette étape a déjà reçu une décision (jeton déjà utilisé).",
        ) from exc
    except decision_tokens.JetonDecisionInvalide as exc:
        await audit.consigner(
            db,
            action="tentative_jeton_invalide",
            acteur_id=current_user.id if current_user else None,
            cible_type="jeton_decision",
            cible_id=None,
            details={"motif": str(exc)},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton de décision invalide ou expiré.",
        ) from exc

    etape_id = jeton_ligne.etape_workflow_id
    action = jeton_ligne.action_autorisee

    if action not in ACTIONS_VALIDES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action inconnue.")

    etape = await db.get(EtapeWorkflow, etape_id)
    if etape is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Étape de workflow introuvable.")

    # Defense en profondeur (section 8) : une etape de role Signataire ne
    # doit jamais pouvoir etre decidee via "approuver" - meme si un jeton
    # de ce type existait par erreur (regression future, jeton forge a la
    # main...). En pratique, un tel jeton n'est jamais genere pour ce role
    # (voir plus bas dans ce fichier, generation du jeton d'escalade), mais
    # cette verification ne depend pas de cette seule garantie.
    if etape.role == RoleEtape.SIGNATAIRE and action == "approuver":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette étape exige une signature (action « signer »), pas une simple approbation.",
        )

    # Le jeton n'est valable qu'une fois : au-dela, l'etape n'est plus EN_ATTENTE.
    # (Deuxieme garde-fou, independant de `utilise_a` ci-dessus - couvre le cas
    # ou un autre jeton, ex. l'action opposee sur la meme etape, a deja ete
    # consomme en premier.)
    # Ecart identifie et corrige (revue du 27/09) : ce message etait le meme
    # que l'etape soit deja decidee OU simplement en discussion (ecart n°5,
    # section 4.5 - app/routers/clarifications.py:suspendre_pour_precisions),
    # ce qui induisait en erreur un approbateur qui vient de suspendre le
    # circuit lui-meme (message correct pour un tiers reutilisant un vieux
    # jeton, trompeur pour l'auteur de la suspension).
    if etape.statut == StatutEtape.EN_COURS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cette étape est en attente de précisions (discussion en cours) : "
                "reprenez le workflow avant de décider."
            ),
        )
    if etape.statut != StatutEtape.EN_ATTENTE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette étape a déjà reçu une décision (jeton déjà utilisé).",
        )

    # --- Option B (section 9.1) : session active exigee et correspondance avec l'approbateur attendu. ---
    if settings.decision_requires_active_session:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Connexion requise pour confirmer cette décision.",
            )
        if current_user.id != etape.approbateur_attendu_id:
            await audit.consigner(
                db,
                action="tentative_decision_usurpation",
                acteur_id=current_user.id,
                cible_type="etape_workflow",
                cible_id=etape.id,
                details={"approbateur_attendu": str(etape.approbateur_attendu_id)},
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cette décision ne vous est pas destinée.",
            )

    # Commentaire de rejet obligatoire et bloquant (CDC fonctionnel, section 2.3).
    if action == "refuser" and not (payload.commentaire and payload.commentaire.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un commentaire est obligatoire en cas de refus.",
        )

    # Signature obligatoire et bloquante pour le role Signataire (section 8 :
    # "Capturer une signature à l'écran, ou refuser") - seule l'action
    # "signer" atteint ce point (un jeton "approuver" n'est jamais genere
    # pour une etape de ce role, voir plus bas dans ce fichier).
    signature_octets: bytes | None = None
    if action == "signer":
        if not payload.signature_image_base64:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Une signature est obligatoire pour valider cette étape.",
            )
        try:
            signature_octets = base64.b64decode(payload.signature_image_base64, validate=True)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Image de signature invalide (base64 attendu).",
            ) from exc
        if not signature_octets:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Image de signature vide.",
            )
        try:
            signature.valider_signature_png(signature_octets)
        except signature.SignatureInvalide as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # Justification d'acceptation obligatoire et bloquante pour approuver
    # une etape d'arbitrage exceptionnel (section 4.4 - derogation motivee
    # ou depassement budgetaire detecte automatiquement). Jamais exigee
    # pour un refus (deja couvert par le commentaire obligatoire ci-dessus)
    # ni pour une decision ordinaire (etape.est_derogation == False).
    if etape.est_derogation and action in ("approuver", "signer"):
        if not (payload.justification_acceptation and payload.justification_acceptation.strip()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Une justification d'acceptation est obligatoire pour valider une dérogation.",
            )

    demande = await db.get(Demande, etape.demande_id)

    # Ecart identifié : une demande annulée entre-temps par le demandeur
    # (route d'annulation) ne doit plus pouvoir être décidée, même si le
    # jeton et l'étape sont encore techniquement EN_ATTENTE.
    if demande.statut_global != StatutDemande.EN_COURS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette demande n'est plus active (annulée ou déjà clôturée).",
        )

    # --- Etape 14 : mise a jour de l'etape + consommation du jeton (§9.3). ---
    decision_tokens.consommer_jeton_decision(jeton_ligne)
    etape.statut = StatutEtape.APPROUVE if action in ("approuver", "signer") else StatutEtape.REFUSE
    etape.commentaire = payload.commentaire
    etape.date_reponse = datetime.now(UTC)
    if signature_octets is not None:
        etape.signature_cle_stockage = await asyncio.to_thread(
            stockage_fichiers.enregistrer_fichier, signature_octets, "signature.png"
        )

    # --- Etape 15/16 : reevaluation du routage (section 7). ---
    # Un refus termine toujours le circuit immediatement, quel que soit le
    # processus - seule une approbation (ou signature) peut declencher une
    # escalade (notes de frais au-dela du seuil configure).
    etape_suivante = None
    if action in ("approuver", "signer"):
        try:
            etape_suivante = await routing_engine.determiner_etape_suivante(db, demande, etape)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    jeton_approuver_suivant = jeton_refuser_suivant = None
    if action in ("approuver", "signer") and etape_suivante is not None:
        # Escalade (section 7) : le circuit continue, pas de finalisation.
        db.add(etape_suivante)
        await db.flush()
        # Ecart identifie et corrige (revue du 27/09) : role Signataire
        # (section 8) -> jeton "signer", jamais "approuver". C'est ce choix,
        # au moment de la generation du jeton, qui garantit qu'une etape
        # Signataire ne peut jamais etre decidee par un simple "approuver" -
        # aucune verification supplementaire n'est necessaire plus loin.
        action_positive_suivante = (
            "signer" if etape_suivante.role == RoleEtape.SIGNATAIRE else "approuver"
        )
        jeton_approuver_suivant = await decision_tokens.generer_jeton_decision(
            db, etape_suivante.id, action_positive_suivante, etape_suivante.approbateur_attendu_id
        )
        jeton_refuser_suivant = await decision_tokens.generer_jeton_decision(
            db, etape_suivante.id, "refuser", etape_suivante.approbateur_attendu_id
        )
        # demande.statut_global reste EN_COURS (deja le cas, rien a changer ici).
        evenement = EvenementWebhook.ETAPE_APPROUVEE
    elif action in ("approuver", "signer"):
        demande.statut_global = StatutDemande.TERMINEE
        evenement = EvenementWebhook.CIRCUIT_TERMINE
    else:
        demande.statut_global = StatutDemande.REFUSEE
        evenement = EvenementWebhook.ETAPE_REFUSEE

    # R18 : débit / libération / numéro de BC dans la même transaction que la décision.
    await _appliquer_effets_finaux(db, demande, etape_suivante, action)

    await db.commit()
    await db.refresh(etape)
    await db.refresh(demande)
    if etape_suivante is not None:
        await db.refresh(etape_suivante)

    # --- Notification du nouvel approbateur si escalade (best-effort). ---
    if etape_suivante is not None:
        nouvel_approbateur = await db.get(Utilisateur, etape_suivante.approbateur_attendu_id)
        demandeur_escalade = await db.get(Utilisateur, demande.demandeur_id)
        nom_demandeur_escalade = demandeur_escalade.nom_complet if demandeur_escalade else "un employé"
        try:
            if demande.processus == TypeProcessus.NOTES_FRAIS:
                libelle_objet = (
                    f"la note de frais de {escape(nom_demandeur_escalade)} "
                    f"({devises.libelle_montant(demande.donnees, 'montant')})"
                )
                sujet = f"Note de frais à valider (montant élevé) — {nom_demandeur_escalade}"
                motif = "montant supérieur au seuil configuré"
            elif demande.processus == TypeProcessus.ACHATS:
                objet_achat = demande.donnees.get("objet", "")
                libelle_objet = f"la demande d'achat « {escape(objet_achat)} » de {escape(nom_demandeur_escalade)}"
                sujet = f"Demande d'achat à valider — {nom_demandeur_escalade}"
                motif = "avis favorable du service juridique"
            else:
                libelle_objet = f"la demande de {escape(nom_demandeur_escalade)}"
                sujet = f"Demande à valider — {nom_demandeur_escalade}"
                motif = "étape précédente approuvée"

            libelle_action_positive = "Signer" if etape_suivante.role == RoleEtape.SIGNATAIRE else "Approuver"
            resume_budget = await suivi_budgetaire.resume_budgetaire_demande(db, demande, demandeur_escalade)
            bloc_budget = suivi_budgetaire.bloc_html_budget(resume_budget) if resume_budget else ""
            sujet = f"🔔 {sujet}"
            pieces_mail = await pieces_email.preparer(db, demande.id)
            await email_service.envoyer_email(
                destinataire=nouvel_approbateur.email if nouvel_approbateur else "",
                pieces_jointes=pieces_mail.jointes,
                sujet=sujet,
                corps_html=(
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        f"{libelle_objet[:1].upper()}{libelle_objet[1:]} a franchi l'étape précédente avec succès ✅ "
                        f"Elle nécessite maintenant votre validation ({motif})."
                    )
                    + g.carte(_lignes_resume_escalade(demande, nom_demandeur_escalade))
                    + bloc_budget
                    + pieces_email.bloc_html(pieces_mail)
                    + g.boutons(
                        (libelle_action_positive, f"{settings.frontend_base_url}/decisions/{jeton_approuver_suivant}", "primaire"),
                        ("Refuser", f"{settings.frontend_base_url}/decisions/{jeton_refuser_suivant}", "danger"),
                    )
                    + g.note("🔒 Ces liens sont personnels et à usage unique : vous confirmerez votre décision après connexion.")
                ),
            )
        except Exception:
            pass  # section 13.4 : ne doit jamais faire echouer la decision

    # --- Etape 16b (suite) : effets de bord de la finalisation, congés uniquement. ---
    if demande.processus == TypeProcessus.CONGES:
        # Ecart identifié et corrige (revue du 15/09) : dates et duree n'etaient
        # calculees que sur la branche approbation - les notifications de refus
        # (DRH, demandeur) n'avaient donc jamais acces aux dates du conge concerne.
        # `calculer_duree_deductible` est un pur calcul (aucun effet de bord sur
        # le solde), il peut donc etre appele inconditionnellement.
        date_debut = date.fromisoformat(demande.donnees["date_debut"])
        date_fin = date.fromisoformat(demande.donnees["date_fin"])
        nombre_jours = await verrou_rh.calculer_duree_deductible(db, date_debut, date_fin)

        # Le solde a deja ete confirme (ou libere) plus haut, dans la transaction de la decision (R18).
        # La fiche de confirmation d'absence n'est pas generee ici : elle est produite a la demande via
        # GET /api/v1/conges/{id}/fiche-confirmation (app/services/documents.py).

        demandeur = await db.get(Utilisateur, demande.demandeur_id)

        # Ecart identifié : notification DRH réelle (adresses résolues en base),
        # sur l'approbation ET le refus - auparavant un placeholder codé en dur
        # ("rh@example.com"), et uniquement sur l'approbation.
        await _notifier_drh(db, demande, action, demandeur, date_debut, date_fin, nombre_jours)

        # Ecart identifié et corrige (revue du 15/09) : le demandeur lui-meme
        # n'etait jamais notifie de l'issue de sa propre demande - trou direct
        # avec le CDC fonctionnel ("le Demandeur... recoit les notifications
        # d'avancement, approbation finale ou rejet motive").
        await _notifier_demandeur(
            db, demande, action, payload.commentaire, current_user, date_debut, date_fin, nombre_jours
        )

    # --- Effets de bord de la finalisation, notes de frais. ---
    # Uniquement quand le circuit se termine reellement (approuve sans
    # escalade, ou refuse a n'importe quel niveau) - pas au niveau
    # intermediaire d'une escalade (etape_suivante is not None), ou aucune
    # decision definitive n'a encore ete prise sur la depense.
    if demande.processus == TypeProcessus.NOTES_FRAIS and etape_suivante is None:
        # Le budget est debite du montant CONVERTI, fige a la soumission (decision du 28/09) ; les
        # e-mails montrent le montant d'origine, avec son equivalent si la devise differe.
        montant = devises.montant_reference(demande.donnees, "montant")
        montant_txt = devises.libelle_montant(demande.donnees, "montant")
        demandeur = await db.get(Utilisateur, demande.demandeur_id)

        if action == "approuver":
            # Le budget a deja ete debite plus haut, dans la transaction de la decision (R18).

            # Synthese transmise a la comptabilite (CDC fonctionnel 3), une seule fois, a la validation
            # FINALE (jamais a un niveau intermediaire). Un echec d'envoi ne remet JAMAIS en cause la
            # decision deja enregistree : seul l'envoi est protege, et surtout SANS rollback - il
            # expirerait tous les objets ORM que la suite de la route relit (MissingGreenlet, donc un 500
            # renvoye a l'approbateur alors que sa decision est prise). La trace n'est ecrite qu'apres un
            # succes : elle prouve la transmission.
            if settings.comptabilite_email:
                ligne, envoye = None, False
                try:
                    ligne = await synthese_frais.ligne_de(db, demande)
                    if ligne is not None:
                        pieces_mail = await pieces_email.preparer(db, demande.id)
                        await email_service.envoyer_email(
                            destinataire=settings.comptabilite_email,
                            sujet=f"💶 Note de frais validée à rembourser — {ligne.demandeur_nom}",
                            corps_html=synthese_frais.corps_email_html(ligne) + pieces_email.bloc_html(pieces_mail),
                            pieces_jointes=pieces_mail.jointes,
                        )
                        envoye = True
                except Exception:
                    logger.exception("Echec de l'envoi de la synthese a la comptabilite (demande %s)", demande.id)
                if envoye:
                    await audit.consigner(
                        db, action="synthese_comptabilite_envoyee", acteur_id=None, cible_type="demande",
                        cible_id=demande.id, details={"destinataire": settings.comptabilite_email},
                    )
                    await db.commit()

        if demandeur is not None:
            try:
                if action == "approuver":
                    sujet = f"🎉 Votre note de frais de {montant_txt} a été approuvée"
                    corps = (
                        g.paragraphe("Bonjour,")
                        + g.paragraphe(
                            f"Bonne nouvelle : votre note de frais de <strong>{escape(montant_txt)}</strong> a été "
                            "validée 🙌 Elle est transmise à la comptabilité pour remboursement."
                        )
                    )
                else:
                    sujet = f"❌ Votre note de frais de {montant_txt} a été refusée"
                    corps = (
                        g.paragraphe("Bonjour,")
                        + g.paragraphe(
                            f"Votre note de frais de <strong>{escape(montant_txt)}</strong> n'a pas pu être validée."
                        )
                        + g.encart(payload.commentaire or "", "Motif communiqué", "refus", "💬")
                        + g.note("Vous pouvez corriger votre dossier et déposer une nouvelle note de frais.")
                    )
                await email_service.envoyer_email(
                    destinataire=demandeur.email, sujet=sujet, corps_html=corps
                )
            except Exception:
                pass  # section 13.4 : ne doit jamais faire echouer la decision

    # --- Effets de bord de la finalisation, achats. ---
    # Meme structure que les notes de frais : consommation du budget
    # uniquement a la finalisation reelle (etape_suivante is None), jamais
    # au niveau intermediaire (avis du service juridique).
    #
    # Ecart corrige (revue du 27/09) : la signature du role Signataire
    # (Direction generale) est desormais reellement capturee (action
    # "signer", voir plus haut dans ce fichier) - traitee ici exactement
    # comme une approbation pour la finalisation (consommation du budget,
    # numero de bon de commande). Reste hors perimetre : le certificat de
    # validation est une mention imprimee integrant l'image de la
    # signature, pas un certificat cryptographique distinct (voir
    # app/services/documents.py:generer_bon_de_commande).
    if demande.processus == TypeProcessus.ACHATS and etape_suivante is None:
        budget_engage = devises.montant_reference(demande.donnees, "budget_engage")  # debite : converti, fige
        budget_txt = devises.libelle_montant(demande.donnees, "budget_engage")  # affiche : d'origine (+ equivalent)
        demandeur = await db.get(Utilisateur, demande.demandeur_id)

        # Le budget est debite et le numero de bon de commande attribue plus haut, dans la transaction de
        # la decision (R18, R21).

        if demandeur is not None:
            try:
                tiers = demande.donnees.get("tiers", "")
                if action in ("approuver", "signer"):
                    sujet = f"🎉 Votre demande d'achat auprès de {tiers} a été approuvée"
                    if etape.est_derogation:
                        # Circuit standard contourne : ne jamais pretendre que le juridique / la DG ont valide.
                        validation = "Elle a été acceptée en arbitrage exceptionnel (dérogation) ⚖️"
                        note_bc = "📄 Le bon de commande, mentionnant l'arbitrage, est disponible dans « Achats »."
                    else:
                        validation = "L'avis juridique et la validation de la Direction générale sont obtenus ✍️"
                        note_bc = "📄 Le bon de commande signé est disponible dans « Achats »."
                    corps = (
                        g.paragraphe("Bonjour,")
                        + g.paragraphe(
                            f"Excellente nouvelle : votre demande d'achat de <strong>{escape(budget_txt)}</strong> "
                            f"auprès de <strong>{escape(tiers)}</strong> a été approuvée. {validation}"
                        )
                        + g.note(note_bc)
                    )
                else:
                    sujet = f"❌ Votre demande d'achat auprès de {tiers} a été refusée"
                    corps = (
                        g.paragraphe("Bonjour,")
                        + g.paragraphe(
                            f"Votre demande d'achat de <strong>{escape(budget_txt)}</strong> auprès de "
                            f"<strong>{escape(tiers)}</strong> n'a pas pu être validée."
                        )
                        + g.encart(payload.commentaire or "", "Motif communiqué", "refus", "💬")
                    )
                await email_service.envoyer_email(
                    destinataire=demandeur.email, sujet=sujet, corps_html=corps
                )
            except Exception:
                pass  # section 13.4 : ne doit jamais faire echouer la decision

    # --- Etape 17 : webhook sortant si un abonnement existe. ---
    await webhooks.notifier_evenement(db, demande.id, demande.processus, evenement)

    # --- Etape 18 : journal d'audit. ---
    await audit.consigner(
        db,
        action={"approuver": "etape_approuvee", "signer": "etape_signee"}.get(action, "etape_refusee"),
        acteur_id=current_user.id if current_user else None,
        cible_type="etape_workflow",
        cible_id=etape.id,
        details=(
            {"commentaire": payload.commentaire, "justification_acceptation": payload.justification_acceptation}
            if etape.est_derogation
            else {"commentaire": payload.commentaire}
        ),
    )
    await db.commit()

    # --- Etape 19 : confirmation. ---
    return DecisionResponse(
        demande_id=str(demande.id),
        etape_id=str(etape.id),
        action=action,
        statut_global=demande.statut_global.value,
    )
