"""
Annulation et relance manuelle d'une demande, generiques aux trois processus (congés, notes de
frais, achats). Ecart trouve par l'audit de conformite du 28/09 : ces deux actions n'existaient
QUE pour les conges, alors que rien dans le cahier des charges ne les y limite - le tableau de suivi
(§12) et le mecanisme de rappel du §2.4 s'appliquent aux trois processus.

Ne pas confondre la relance MANUELLE (ce module, declenchee par le demandeur ou la DRH quand un
e-mail a ete egare ou n'est jamais arrive) avec les rappels AUTOMATIQUES a echeance fixe
(app/services/rappels.py, §2.4) : les deux revoquent et regenerent les jetons de decision (un seul
couple actif a la fois, CDC technique §9.3) et affichent le meme resume budgetaire au decideur
(§4.3), mais la relance manuelle n'interagit jamais avec les colonnes de reservation du
planificateur (dernier_rappel_le, nombre_rappels) : les deux mecanismes restent independants, sans
se voler mutuellement un passage.
"""
from html import escape

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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
from app.services import audit, decision_tokens, email_gabarit as g, email_service, pieces_email, webhooks
from app.services.extensions import suivi_budgetaire, verrou_rh
from app.services.rappels import LIBELLES_PROCESSUS, resume_html

settings = get_settings()

STATUTS_ANNULABLES = (StatutDemande.EN_COURS, StatutDemande.COMPLEMENT_DEMANDE)


async def annuler(db: AsyncSession, demande: Demande, current_user: Utilisateur) -> dict:
    """
    Retire une demande encore en cours (ou en attente de precisions, ecart n°5 : le demandeur
    doit pouvoir se retirer meme pendant une discussion, pas seulement avant qu'elle ne s'ouvre).
    Les jetons de decision deja envoyes deviennent caducs : la route de decision verifie le statut
    de la demande, pas seulement celui de l'etape.
    """
    if demande.demandeur_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cette demande ne vous appartient pas.")
    if demande.statut_global not in STATUTS_ANNULABLES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seule une demande encore en cours ou en attente de précisions peut être annulée.",
        )

    demande.statut_global = StatutDemande.ANNULEE
    # R17 : une demande de conges annulee rend au solde les jours qu'elle avait reserves, dans la
    # meme transaction que le changement de statut.
    if demande.processus == TypeProcessus.CONGES:
        await verrou_rh.liberer_reservation(db, demande, MotifMouvementConges.LIBERATION_ANNULATION)
    await webhooks.notifier_evenement(db, demande.id, demande.processus, EvenementWebhook.DEMANDE_ANNULEE)
    await audit.consigner(
        db, action="demande_annulee", acteur_id=current_user.id, cible_type="demande", cible_id=demande.id, details={}
    )
    await db.commit()
    return {"id": str(demande.id), "statut_global": demande.statut_global.value}


async def relancer(db: AsyncSession, demande: Demande, current_user: Utilisateur) -> dict:
    """
    Renvoie la notification de decision a l'approbateur en attente, avec de nouveaux jetons.
    Declenchee par le demandeur ou la DRH - par exemple si l'e-mail initial a echoue a l'envoi ou a
    simplement ete egare. Le role de l'etape determine l'action positive proposee : un Signataire
    (ex. Direction Generale sur un achat) recoit un lien "signer", jamais "approuver".
    """
    if demande.demandeur_id != current_user.id and current_user.role != RoleUtilisateur.DRH:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cette demande ne vous appartient pas.")
    if demande.statut_global != StatutDemande.EN_COURS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette demande n'attend plus de décision.")

    resultat = await db.execute(
        select(EtapeWorkflow).where(EtapeWorkflow.demande_id == demande.id, EtapeWorkflow.statut == StatutEtape.EN_ATTENTE)
    )
    etape = resultat.scalars().first()
    if etape is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aucune étape en attente à relancer.")

    approbateur = await db.get(Utilisateur, etape.approbateur_attendu_id)
    demandeur = await db.get(Utilisateur, demande.demandeur_id)

    action_positive = "signer" if etape.role == RoleEtape.SIGNATAIRE else "approuver"
    await decision_tokens.revoquer_jetons_actifs(db, etape.id)
    jeton_positif = await decision_tokens.generer_jeton_decision(db, etape.id, action_positive, etape.approbateur_attendu_id)
    jeton_refus = await decision_tokens.generer_jeton_decision(db, etape.id, "refuser", etape.approbateur_attendu_id)
    await audit.consigner(
        db, action="decision_relancee", acteur_id=current_user.id, cible_type="demande", cible_id=demande.id,
        details={"relance_par": str(current_user.id)},
    )
    await db.commit()

    email_envoye = True
    if approbateur is not None:
        try:
            resume_budget = await suivi_budgetaire.resume_budgetaire_demande(db, demande, demandeur)
            libelle_positif = "Signer" if action_positive == "signer" else "Approuver"
            qualificatifs = []
            if etape.est_derogation:
                qualificatifs.append("arbitrage exceptionnel (dérogation)")
            if etape.role == RoleEtape.SIGNATAIRE:
                qualificatifs.append("signature requise")
            pieces_mail = await pieces_email.preparer(db, demande.id)
            await email_service.envoyer_email(
                destinataire=approbateur.email,
                pieces_jointes=pieces_mail.jointes,
                sujet=f"⏰ Rappel — {LIBELLES_PROCESSUS[demande.processus]} à valider — {demandeur.nom_complet}",
                corps_html=(
                    g.paragraphe("Bonjour,")
                    + g.paragraphe(
                        f"Un petit rappel 🌟 : une {LIBELLES_PROCESSUS[demande.processus]} de "
                        f"<strong>{escape(demandeur.nom_complet)}</strong> attend toujours votre décision"
                        f"{' — ' + ', '.join(qualificatifs) if qualificatifs else ''}."
                    )
                    + f'<ul style="margin:0 0 16px 18px;padding:0;font-size:14.5px;line-height:1.6;color:#1f2430;">{resume_html(demande)}</ul>'
                    + (suivi_budgetaire.bloc_html_budget(resume_budget) if resume_budget else "")
                    + pieces_email.bloc_html(pieces_mail)
                    + g.boutons(
                        (libelle_positif, f"{settings.frontend_base_url}/decisions/{jeton_positif}", "primaire"),
                        ("Refuser", f"{settings.frontend_base_url}/decisions/{jeton_refus}", "danger"),
                    )
                    + g.note("🔄 Les liens envoyés précédemment ne sont plus valables : utilisez ceux-ci.")
                ),
            )
        except Exception:
            email_envoye = False

    return {
        "id": str(demande.id),
        "email_envoye": email_envoye,
        "detail": (
            "Notification renvoyée à l'approbateur."
            if email_envoye
            else "L'e-mail n'a pas pu être envoyé — réessayez plus tard ou contactez l'approbateur directement."
        ),
    }
