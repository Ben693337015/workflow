"""
Routes du processus "Notes de frais" (section 3 / 7 / 11 du CDC technique).

Reutilise la meme infrastructure generique que les conges (Demande /
EtapeWorkflow / jetons de decision / routing_engine / webhooks / audit -
app/routers/conges.py) plutot que de la dupliquer. Deux ecarts reels avec
le circuit conges :
- Suivi budgetaire (section 11, ecart n3) : verification synchrone AVANT
  creation, meme principe que le verrou RH des conges (section 13.2,
  etape 4).
- Routage conditionnel sur le montant (section 7) : au-dela du seuil
  configure (Settings.notes_frais_seuil_direction_financiere), un second
  niveau d'approbation est ajoute (Direction financiere) - voir
  app/services/routing_engine.py:determiner_etape_suivante, appele
  depuis app/routers/decisions.py apres une approbation de niveau 1.
"""
import uuid
from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.demande import Demande
from app.models.enums import EvenementWebhook, StatutDemande, TypeProcessus
from app.models.user import Utilisateur
from app.schemas.notes_frais import NoteFraisCreate, NoteFraisRead, SoumissionNotesFraisResponse
from app.services import devises, gestion_demandes, pieces, audit, decision_tokens, email_gabarit as g, email_service, routing_engine, webhooks
from app.services.extensions import suivi_budgetaire

router = APIRouter(prefix="/api/v1/notes-frais", tags=["notes_frais"])
settings = get_settings()


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=SoumissionNotesFraisResponse)
async def soumettre_note_de_frais(
    payload: NoteFraisCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    exercice = payload.date_depense.year

    # --- Conversion dans la devise de reference (decision du 28/09 : plusieurs devises). ---
    # Le budget, le seuil d'escalade et les soldes sont exprimes dans cette devise. Le taux retenu est
    # celui en vigueur a la date de la depense ; il est FIGE sur la demande (voir devises.py).
    try:
        conversion = await devises.convertir(db, payload.montant, payload.devise, payload.date_depense)
    except devises.TauxIntrouvable as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    montant_ref = conversion.montant_reference
    ref = devises.devise_reference()

    # --- Verification synchrone AVANT toute creation (meme principe que
    # le verrou RH des conges, section 13.2 etape 4). ---
    # Ecart n°4 (section 4.4 du CDC fonctionnel) corrige : un depassement
    # budgetaire ne bloque plus la soumission (ancien comportement, avant
    # cette revue) - il declenche desormais le meme detournement vers
    # l'arbitrage exceptionnel qu'une derogation motivee cochee par le
    # demandeur ("Si... OU si le systeme de controle budgetaire detecte un
    # depassement de l'enveloppe du service, le flux doit etre
    # immediatement detourne").
    budget_ok, solde_disponible = await suivi_budgetaire.budget_suffisant(
        db, current_user.service, exercice, montant_ref
    )
    derogation_necessaire = payload.derogation_motivee or not budget_ok
    if derogation_necessaire and not (payload.motif_derogation and payload.motif_derogation.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Budget insuffisant pour le service « {current_user.service} » "
                f"({exercice}) : {devises.formater(montant_ref, ref)} demandé(s) pour "
                f"{devises.formater(solde_disponible, ref)} disponible(s) - un motif de dérogation "
                f"est obligatoire pour soumettre malgré tout."
            ),
        )

    demande = Demande(
        processus=TypeProcessus.NOTES_FRAIS,
        demandeur_id=current_user.id,
        initiee_par_id=current_user.id,
        donnees={
            **payload.model_dump(mode="json"),
            "devise": conversion.devise,
            "taux_applique": conversion.taux,
            "montant_reference": montant_ref,
        },
        statut_global=StatutDemande.EN_COURS,
    )
    db.add(demande)
    await db.flush()

    try:
        if derogation_necessaire:
            etape = await routing_engine.determiner_etape_derogation(db, demande)
        else:
            etape = await routing_engine.determiner_premiere_etape(db, demande, current_user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                str(exc)
                if derogation_necessaire
                else "Aucun manager n'est rattaché à votre compte : contactez la DRH avant de soumettre une note de frais."
            ),
        ) from exc
    db.add(etape)
    await db.flush()

    jeton_approuver = await decision_tokens.generer_jeton_decision(
        db, etape.id, "approuver", etape.approbateur_attendu_id
    )
    jeton_refuser = await decision_tokens.generer_jeton_decision(
        db, etape.id, "refuser", etape.approbateur_attendu_id
    )

    await db.commit()
    await db.refresh(demande)
    await db.refresh(etape)

    manager = await db.get(Utilisateur, etape.approbateur_attendu_id)
    try:
        montant_txt = devises.libelle_montant(demande.donnees, 'montant')
        if derogation_necessaire:
            sujet = f"⚖️ Arbitrage requis (dérogation) — {current_user.nom_complet}"
            intro = (
                f"<strong>{escape(current_user.nom_complet)}</strong> ({escape(current_user.service)}) a soumis une "
                f"note de frais de <strong>{escape(montant_txt)}</strong> qui demande un arbitrage exceptionnel "
                f"{'(dérogation motivée)' if payload.derogation_motivee else '(dépassement budgétaire détecté automatiquement)'}."
            )
            detail = g.encart(payload.motif_derogation or "", "Motif de la dérogation", "attention", "⚖️")
        else:
            sujet = f"🧾 Nouvelle note de frais à valider — {current_user.nom_complet}"
            intro = (
                f"<strong>{escape(current_user.nom_complet)}</strong> ({escape(current_user.service)}) vous a adressé une "
                f"note de frais de <strong>{escape(montant_txt)}</strong> et attend votre décision 🙌"
            )
            detail = g.carte([
                ("Catégorie", payload.categorie),
                ("Date de la dépense", payload.date_depense.strftime('%d/%m/%Y')),
                ("Description", payload.description),
            ])
        # CDC 4.3 : le solde budgetaire disponible doit etre montre au decideur
        # dans sa notification de vote (avant, aucun decideur ne le voyait).
        resume_budget = await suivi_budgetaire.resume_budgetaire(
            db, current_user.service, exercice, montant_ref
        )
        await email_service.envoyer_email(
            destinataire=manager.email if manager else "",
            sujet=sujet,
            corps_html=(
                g.paragraphe("Bonjour,")
                + g.paragraphe(intro)
                + detail
                + suivi_budgetaire.bloc_html_budget(resume_budget)
                + g.boutons(
                    ("Approuver", f"{settings.frontend_base_url}/decisions/{jeton_approuver}", "primaire"),
                    ("Refuser", f"{settings.frontend_base_url}/decisions/{jeton_refuser}", "danger"),
                )
                + g.note("🔒 Ces liens sont personnels et à usage unique : vous confirmerez votre décision après connexion.")
            ),
        )
    except Exception:
        pass  # section 13.4 : ne doit jamais faire echouer la soumission

    await webhooks.notifier_evenement(
        db,
        demande.id,
        TypeProcessus.NOTES_FRAIS,
        EvenementWebhook.DEROGATION_DECLENCHEE if derogation_necessaire else EvenementWebhook.DEMANDE_SOUMISE,
    )

    await audit.consigner(
        db,
        action="demande_soumise",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={
            "processus": "notes_frais",
            "montant": payload.montant,
            "devise": conversion.devise,
            "montant_reference": montant_ref,
            "derogation": derogation_necessaire,
            "motif_derogation": payload.motif_derogation,
        },
    )
    await db.commit()

    return SoumissionNotesFraisResponse(
        id=str(demande.id),
        statut_global=demande.statut_global.value,
        premiere_etape_id=str(etape.id),
        derogation=derogation_necessaire,
        devise=conversion.devise,
        taux_applique=conversion.taux,
        montant_reference=montant_ref,
    )


@router.get("/", response_model=list[NoteFraisRead])
async def lister_mes_notes_de_frais(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    resultat = await db.execute(
        select(Demande)
        .where(Demande.processus == TypeProcessus.NOTES_FRAIS, Demande.demandeur_id == current_user.id)
        .order_by(Demande.creee_le.desc())
    )
    demandes = resultat.scalars().all()
    pieces_par_id = await pieces.pieces_par_demande(db, [d.id for d in demandes])
    return [
        NoteFraisRead(
            id=str(d.id),
            statut_global=d.statut_global.value,
            donnees=d.donnees,
            creee_le=d.creee_le.isoformat() if d.creee_le else None,
            pieces_jointes=pieces_par_id.get(d.id, []),
        )
        for d in demandes
    ]


@router.post("/{demande_id}/annuler")
async def annuler_note_de_frais(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Annule une note de frais encore en cours. Parité avec les congés (écart corrigé le 28/09,
    cette action n'existait que pour eux) : app/services/gestion_demandes.py."""
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.NOTES_FRAIS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return await gestion_demandes.annuler(db, demande, current_user)


@router.post("/{demande_id}/relancer")
async def relancer_note_de_frais(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Relance manuelle (à distinguer des rappels automatiques, §2.4). Parité avec les congés :
    app/services/gestion_demandes.py."""
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.NOTES_FRAIS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return await gestion_demandes.relancer(db, demande, current_user)
