"""
Routes du processus "Validation d'achats et contrats" (section 3 / 7 / 11
du CDC technique).

Reutilise la meme infrastructure generique que les conges et les notes de
frais (Demande / EtapeWorkflow / jetons de decision / routing_engine /
webhooks / audit) plutot que de la dupliquer. Ecart avec ces deux
processus : aucun manager n'intervient dans le routage (CDC section 3) -
le circuit est fixe, sans logique conditionnelle : avis du Service
juridique, puis toujours signature de la Direction generale (role
Signataire, section 8).

Ecarts trouves et corriges (revue du 27/09) : "Fichier du contrat" (une
des quatre donnees cles a capturer, section 3) et le bon de commande final
("Document contractuel revetu des signatures electroniques avec son
certificat de validation", meme section - ecart n°1, section 4.1 du CDC
technique) n'existaient pas du tout. Les deux sont desormais reels : depot
du contrat a la soumission (app/services/stockage_fichiers.py), bon de
commande genere a la demande apres finalisation (app/services/documents.py).

Ecart supplementaire trouve et corrige (revue du 27/09, suite) : le role
Signataire (section 8 - "Capturer une signature a l'ecran, ou refuser")
etait traite comme un simple Approbateur (meme action "approuver", aucune
signature capturee). Une action "signer" distincte existe desormais,
avec capture reelle d'une image de signature (voir app/routers/decisions.py) -
jamais de jeton "approuver" genere pour ce role, et une verification
defensive rejette explicitement un tel jeton s'il existait malgre tout.

Perimetre delibere encore non couvert : le certificat de validation reste
une mention imprimee (horodatage et identites des deux decideurs), pas un
certificat cryptographique distinct liant la signature au document.
"""
from datetime import UTC, datetime
from html import escape
import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.demande import Demande
from app.models.enums import EvenementWebhook, RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.models.user import Utilisateur
from app.schemas.achats import DemandeAchatCreate, DemandeAchatRead, SoumissionAchatResponse
from app.services import devises, facturation, gestion_demandes, pieces, pieces_email, audit, decision_tokens, documents, email_gabarit as g, email_service, routing_engine, webhooks
from app.services.extensions import suivi_budgetaire
from app.services import stockage_fichiers

router = APIRouter(prefix="/api/v1/achats", tags=["achats"])
settings = get_settings()

def _acces_autorise_piece_jointe(demande: Demande, current_user: Utilisateur) -> bool:
    """
    Le demandeur et les deux niveaux d'approbation (service juridique,
    direction générale) doivent pouvoir consulter le contrat déposé ; la
    DRH également, à des fins d'audit. Pas de restriction plus fine
    (par étape précise) : un contrat approuvé reste consultable après
    décision, pas seulement pendant que l'étape est en attente.
    """
    return current_user.id == demande.demandeur_id or current_user.role in (
        RoleUtilisateur.SERVICE_JURIDIQUE,
        RoleUtilisateur.DIRECTION_GENERALE,
        RoleUtilisateur.DRH,
    )


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=SoumissionAchatResponse)
async def soumettre_demande_achat(
    tiers: str = Form(..., min_length=1, max_length=200),
    objet: str = Form(..., min_length=1, max_length=500),
    budget_engage: float | None = Form(None, gt=0),
    lignes: str | None = Form(None, description="Détail des lignes de la commande, encodé en JSON."),
    devise: str | None = Form(None, min_length=3, max_length=3),
    derogation_motivee: bool = Form(False),
    motif_derogation: str | None = Form(None, max_length=1000),
    fichier_contrat: UploadFile = File(..., description="Fichier du contrat."),
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    lignes_donnees = None
    if lignes:
        # Un formulaire multipart ne transporte que du texte : le detail des lignes voyage en JSON
        # dans ce champ, valide ensuite par le meme schema Pydantic que le reste du payload.
        try:
            lignes_donnees = json.loads(lignes)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Le détail des lignes n'est pas un JSON valide."
            ) from exc

    try:
        payload = DemandeAchatCreate(
            tiers=tiers,
            objet=objet,
            budget_engage=budget_engage,
            lignes=lignes_donnees,
            devise=devise,
            derogation_motivee=derogation_motivee,
            motif_derogation=motif_derogation,
        )
    except ValidationError as exc:
        # Ecart trouve et corrige (revue du 27/09) : `payload` est construit
        # ici a la main (champs Form, pas un corps JSON gere par FastAPI) -
        # sans ce bloc, une ValidationError (ex. motif de derogation
        # manquant) remontait en 500 au lieu d'un 422 propre, contrairement
        # a app/routers/notes_frais.py ou le meme validateur est declenche
        # automatiquement par FastAPI (payload declare directement en
        # parametre de la route, corps JSON).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors()[0]["msg"] if exc.errors() else str(exc),
        ) from exc

    contenu_contrat = await stockage_fichiers.lire_depot(fichier_contrat)
    erreur_fichier = stockage_fichiers.verifier_fichier(fichier_contrat.content_type, contenu_contrat)
    if erreur_fichier:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=erreur_fichier)

    # Detail par ligne (28/09) : le budget engage n'est alors plus saisi directement - il est
    # DEDUIT du total TTC des lignes, pour qu'un seul montant fasse foi (jamais deux chiffres
    # qui pourraient diverger). Sans lignes, le montant saisi reste utilise tel quel (retrocompatibilite).
    budget_effectif = (
        facturation.somme_ttc([l.model_dump() for l in payload.lignes]) if payload.lignes else payload.budget_engage
    )

    exercice = datetime.now(UTC).year

    # Conversion dans la devise de reference, au taux du jour, fige sur la demande (voir devises.py).
    try:
        conversion = await devises.convertir(db, budget_effectif, payload.devise, datetime.now(UTC).date())
    except devises.TauxIntrouvable as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    budget_ref = conversion.montant_reference
    ref = devises.devise_reference()

    # Ecart n°4 (section 4.4 du CDC fonctionnel) corrige : voir le meme
    # commentaire dans app/routers/notes_frais.py - un depassement
    # budgetaire detourne desormais vers l'arbitrage exceptionnel plutot
    # que de bloquer purement et simplement la soumission.
    budget_ok, solde_disponible = await suivi_budgetaire.budget_suffisant(
        db, current_user.service, exercice, budget_ref
    )
    derogation_necessaire = payload.derogation_motivee or not budget_ok
    if derogation_necessaire and not (payload.motif_derogation and payload.motif_derogation.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Budget insuffisant pour le service « {current_user.service} » "
                f"({exercice}) : {devises.formater(budget_ref, ref)} demandé(s) pour "
                f"{devises.formater(solde_disponible, ref)} disponible(s) - un motif de dérogation "
                f"est obligatoire pour soumettre malgré tout."
            ),
        )

    demande = Demande(
        processus=TypeProcessus.ACHATS,
        demandeur_id=current_user.id,
        initiee_par_id=current_user.id,
        donnees={
            **payload.model_dump(mode="json"),
            "budget_engage": budget_effectif,  # deduit des lignes le cas echeant : source unique de verite
            "devise": conversion.devise,
            "taux_applique": conversion.taux,
            "budget_engage_reference": budget_ref,
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
            detail=str(exc),
        ) from exc
    db.add(etape)
    await db.flush()

    # Depot du contrat (section 3, donnee cle "Fichier du contrat") -
    # ecrit sur disque APRES que le routage a reussi (pas de fichier
    # orphelin si la demande finit par etre rejetee a la creation).
    cle_stockage = await asyncio.to_thread(
        stockage_fichiers.enregistrer_fichier, contenu_contrat, fichier_contrat.filename or "contrat"
    )
    piece_jointe = PieceJointe(
        demande_id=demande.id,
        nom_original=fichier_contrat.filename or "contrat",
        cle_stockage=cle_stockage,
        categorie=CategoriePiece.CONTRAT.value,
    )
    db.add(piece_jointe)
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

    juriste = await db.get(Utilisateur, etape.approbateur_attendu_id)
    try:
        montant_txt = devises.libelle_montant(demande.donnees, 'budget_engage')
        if derogation_necessaire:
            sujet = f"⚖️ Arbitrage requis (dérogation) — {current_user.nom_complet}"
            intro = (
                f"<strong>{escape(current_user.nom_complet)}</strong> ({escape(current_user.service)}) a soumis une "
                f"demande d'achat auprès de <strong>{escape(payload.tiers)}</strong> ({escape(montant_txt)}) qui demande "
                f"un arbitrage exceptionnel "
                f"{'(dérogation motivée)' if payload.derogation_motivee else '(dépassement budgétaire détecté automatiquement)'}."
            )
            detail = g.encart(payload.motif_derogation or "", "Motif de la dérogation", "attention", "⚖️")
        else:
            sujet = f"🛒 Avis juridique requis — demande d'achat de {current_user.nom_complet}"
            intro = (
                f"<strong>{escape(current_user.nom_complet)}</strong> ({escape(current_user.service)}) a déposé une "
                f"demande d'achat auprès de <strong>{escape(payload.tiers)}</strong> ({escape(montant_txt)}) et sollicite "
                f"votre avis juridique sur le contrat 📑"
            )
            detail = g.carte([("Objet de la dépense", payload.objet)])
        # CDC 4.3 : solde budgetaire montre au decideur (voir notes_frais.py).
        resume_budget = await suivi_budgetaire.resume_budgetaire(
            db, current_user.service, exercice, budget_ref
        )
        pieces_mail = await pieces_email.preparer(db, demande.id)
        await email_service.envoyer_email(
            destinataire=juriste.email if juriste else "",
            pieces_jointes=pieces_mail.jointes,
            sujet=sujet,
            corps_html=(
                g.paragraphe("Bonjour,")
                + g.paragraphe(intro)
                + detail
                + suivi_budgetaire.bloc_html_budget(resume_budget)
                + pieces_email.bloc_html(pieces_mail)
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
        TypeProcessus.ACHATS,
        EvenementWebhook.DEROGATION_DECLENCHEE if derogation_necessaire else EvenementWebhook.DEMANDE_SOUMISE,
    )

    await audit.consigner(
        db,
        action="demande_soumise",
        acteur_id=current_user.id,
        cible_type="demande",
        cible_id=demande.id,
        details={
            "processus": "achats",
            "budget_engage": budget_effectif,
            "devise": conversion.devise,
            "budget_engage_reference": budget_ref,
            "derogation": derogation_necessaire,
            "motif_derogation": payload.motif_derogation,
        },
    )
    await db.commit()

    return SoumissionAchatResponse(
        id=str(demande.id),
        statut_global=demande.statut_global.value,
        premiere_etape_id=str(etape.id),
        derogation=derogation_necessaire,
        devise=conversion.devise,
        taux_applique=conversion.taux,
        budget_engage_reference=budget_ref,
    )


@router.get("/", response_model=list[DemandeAchatRead])
async def lister_mes_demandes_achat(
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    resultat = await db.execute(
        select(Demande)
        .where(Demande.processus == TypeProcessus.ACHATS, Demande.demandeur_id == current_user.id)
        .order_by(Demande.creee_le.desc())
    )
    demandes = resultat.scalars().all()
    pieces_par_id = await pieces.pieces_par_demande(db, [d.id for d in demandes])
    return [
        DemandeAchatRead(
            id=str(d.id),
            statut_global=d.statut_global.value,
            donnees=d.donnees,
            creee_le=d.creee_le.isoformat() if d.creee_le else None,
            pieces_jointes=pieces_par_id.get(d.id, []),
        )
        for d in demandes
    ]


async def _resoudre_demande_achat(db: AsyncSession, demande_id: str) -> Demande:
    """
    Convertit l'identifiant de chemin (chaîne) en uuid.UUID avant toute
    requête - `db.get(Demande, demande_id)` avec une chaîne brute échoue
    au niveau du pilote SQL (attend un objet UUID, pas son texte), erreur
    trouvée et corrigée en écrivant les tests de ces deux routes.
    """
    try:
        identifiant = uuid.UUID(demande_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande d'achat introuvable.")
    demande = await db.get(Demande, identifiant)
    if demande is None or demande.processus != TypeProcessus.ACHATS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande d'achat introuvable.")
    return demande


@router.get("/{demande_id}/piece-jointe")
async def telecharger_piece_jointe_contrat(
    demande_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    demande = await _resoudre_demande_achat(db, demande_id)
    if not _acces_autorise_piece_jointe(demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce document.")

    resultat = await db.execute(
        select(PieceJointe)
        .where(PieceJointe.demande_id == demande.id, PieceJointe.categorie == CategoriePiece.CONTRAT.value)
        .order_by(PieceJointe.deposee_le.desc())
    )
    piece = resultat.scalars().first()
    if piece is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun contrat déposé pour cette demande.")

    contenu = await asyncio.to_thread(stockage_fichiers.lire_fichier, piece.cle_stockage)
    return Response(
        content=contenu,
        media_type="application/octet-stream",
        headers={"Content-Disposition": stockage_fichiers.en_tete_telechargement(piece.nom_original)},
    )


@router.get("/{demande_id}/bon-de-commande")
async def telecharger_bon_de_commande(
    demande_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """
    Livrable final (section 3 : "Document contractuel revêtu des
    signatures électroniques avec son certificat de validation" ; écart
    n°1, section 4.1 du CDC technique). Généré à la demande, comme la
    fiche de confirmation d'absence des congés (app/services/documents.py)
    - même choix architectural, mêmes raisons (pas de stockage persistant
    de fichiers générés tant que NubiS3 n'est pas raccordé).

    N'existe que si la demande est réellement terminée (numéro de bon de
    commande attribué à la finalisation, app/routers/decisions.py) - pas
    de génération anticipée d'un document qui n'a pas encore d'existence
    juridique.
    """
    demande = await _resoudre_demande_achat(db, demande_id)
    if not _acces_autorise_piece_jointe(demande, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce document.")
    if demande.statut_global != StatutDemande.TERMINEE or "numero_bc" not in demande.donnees:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette demande d'achat n'a pas encore été validée jusqu'à son terme.",
        )

    resultat = await db.execute(
        select(EtapeWorkflow)
        .where(EtapeWorkflow.demande_id == demande.id)
        .order_by(EtapeWorkflow.niveau)
    )
    etapes = resultat.scalars().all()
    juriste_id = next((e.approbateur_attendu_id for e in etapes if e.niveau == 1), None)
    signataire_id = next((e.approbateur_attendu_id for e in etapes if e.niveau == 2), None)
    juriste = await db.get(Utilisateur, juriste_id) if juriste_id else None
    signataire = await db.get(Utilisateur, signataire_id) if signataire_id else None
    date_signature = next(
        (e.date_reponse for e in etapes if e.niveau == 2 and e.date_reponse), None
    )
    cle_signature = next(
        (e.signature_cle_stockage for e in etapes if e.niveau == 2 and e.signature_cle_stockage), None
    )
    signature_image = await asyncio.to_thread(stockage_fichiers.lire_fichier, cle_signature) if cle_signature else None

    # Derogation : un seul arbitre a decide, a la place du juridique et de la Direction generale.
    etape_arbitrage = next((e for e in etapes if e.est_derogation), None)
    arbitre = (
        await db.get(Utilisateur, etape_arbitrage.approbateur_attendu_id) if etape_arbitrage is not None else None
    )
    pdf = documents.generer_bon_de_commande(
        demande=demande,
        juriste=juriste,
        signataire=signataire,
        date_signature=date_signature,
        signature_image=signature_image,
        arbitre=arbitre,
        date_arbitrage=etape_arbitrage.date_reponse if etape_arbitrage is not None else None,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{demande.donnees["numero_bc"]}.pdf"'
        },
    )


@router.post("/{demande_id}/annuler")
async def annuler_demande_achat(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Annule une demande d'achat encore en cours. Parité avec les congés (écart corrigé le 28/09,
    cette action n'existait que pour eux) : app/services/gestion_demandes.py."""
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.ACHATS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return await gestion_demandes.annuler(db, demande, current_user)


@router.post("/{demande_id}/relancer")
async def relancer_demande_achat(
    demande_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    """Relance manuelle (à distinguer des rappels automatiques, §2.4). Le second niveau (Direction
    Générale) est Signataire : reçoit un lien "signer", jamais "approuver" (voir gestion_demandes.relancer).
    Parité avec les congés : app/services/gestion_demandes.py."""
    demande = await db.get(Demande, demande_id)
    if demande is None or demande.processus != TypeProcessus.ACHATS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable.")
    return await gestion_demandes.relancer(db, demande, current_user)
