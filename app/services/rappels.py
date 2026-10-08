"""
Rappels automatiques des decisions en attente (CDC fonctionnel 2.4 : "un
mecanisme de relance automatique relancant les dossiers en attente selon une
frequence parametrable (ex. toutes les 48 heures)").

Ce mecanisme n'existait pas : seule la relance manuelle des conges etait
implementee, et le tableau de couverture du CDC technique (17.1) le declarait
pourtant couvert (ecart trouve par l'audit de conformite du 28/09).

Principes :
- Generique aux trois processus : une etape EN_ATTENTE dont la demande est
  EN_COURS. Une etape en discussion (statut EN_COURS, ecart n°5) n'est jamais
  relancee : l'approbateur a lui-meme suspendu sa decision.
- Sans doublon meme avec plusieurs instances du backend : le rappel est
  RESERVE par un UPDATE conditionnel sur l'instant du dernier rappel avant
  l'envoi ; une seule instance obtient la ligne.
- Un rappel qui echoue n'est pas perdu et ne casse rien : la reservation est
  restauree (nouvel essai au prochain passage) et les anciens liens de decision
  restent valables - ils ne sont revoques que si l'e-mail part reellement.
- Chaque rappel est consigne au journal d'audit ("relance", CDC 2.4).
"""
import logging
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.demande import Demande
from app.models.enums import RoleEtape, StatutDemande, StatutEtape, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.services import audit, decision_tokens, devises, email_gabarit as g, email_service, pieces_email
from app.services.extensions import suivi_budgetaire

logger = logging.getLogger(__name__)
settings = get_settings()

# Utilise aussi par app/services/gestion_demandes.py (relance manuelle) : nom volontairement partage,
# sans le prefixe prive habituel, pour signaler que ce n'est plus interne a ce seul module.
LIBELLES_PROCESSUS = {
    TypeProcessus.CONGES: "demande de congés",
    TypeProcessus.NOTES_FRAIS: "note de frais",
    TypeProcessus.ACHATS: "demande d'achat",
}


def resume_html(demande: Demande) -> str:
    d = demande.donnees
    if demande.processus == TypeProcessus.CONGES:
        lignes = [f"Du {escape(str(d.get('date_debut', '')))} au {escape(str(d.get('date_fin', '')))}"]
        if d.get("commentaire"):
            lignes.append(f"Commentaire du demandeur : {escape(str(d['commentaire']))}")
    elif demande.processus == TypeProcessus.NOTES_FRAIS:
        lignes = [
            f"{escape(devises.libelle_montant(d, 'montant'))} — {escape(str(d.get('categorie', '')))} "
            f"({escape(str(d.get('date_depense', '')))})"
        ]
    else:
        lignes = [f"{escape(str(d.get('tiers', '')))} — {escape(devises.libelle_montant(d, 'budget_engage'))}"]
        if d.get("objet"):
            lignes.append(escape(str(d["objet"])))
    if d.get("motif_derogation"):
        lignes.append(f"Motif de dérogation : {escape(str(d['motif_derogation']))}")
    return "".join(f"<li>{ligne}</li>" for ligne in lignes)


def _aware(valeur: datetime) -> datetime:
    """SQLite restitue des datetimes naifs (UTC) ; PostgreSQL des datetimes avec fuseau."""
    return valeur if valeur.tzinfo else valeur.replace(tzinfo=UTC)


async def _reserver(db: AsyncSession, etape_id, maintenant: datetime, seuil: datetime) -> bool:
    """Reserve atomiquement le rappel : vrai pour une seule instance, meme en cas d'appels simultanes."""
    resultat = await db.execute(
        update(EtapeWorkflow)
        .where(
            EtapeWorkflow.id == etape_id,
            EtapeWorkflow.statut == StatutEtape.EN_ATTENTE,
            func.coalesce(EtapeWorkflow.dernier_rappel_le, EtapeWorkflow.cree_le) <= seuil,
        )
        .values(dernier_rappel_le=maintenant, nombre_rappels=EtapeWorkflow.nombre_rappels + 1)
    )
    await db.commit()
    return resultat.rowcount == 1


async def _restaurer(db: AsyncSession, etape_id, precedent: datetime | None, nombre_avant: int) -> None:
    await db.execute(
        update(EtapeWorkflow)
        .where(EtapeWorkflow.id == etape_id)
        .values(dernier_rappel_le=precedent, nombre_rappels=nombre_avant)
    )
    await db.commit()


async def _rappeler(db: AsyncSession, etape_id, maintenant: datetime, seuil: datetime) -> bool:
    etape = await db.get(EtapeWorkflow, etape_id)
    precedent, nombre_avant = etape.dernier_rappel_le, etape.nombre_rappels

    if not await _reserver(db, etape_id, maintenant, seuil):
        return False  # une autre instance l'a deja traite (ou l'etape a ete decidee entre-temps)

    try:
        await db.refresh(etape)
        demande = await db.get(Demande, etape.demande_id)
        demandeur = await db.get(Utilisateur, demande.demandeur_id)
        approbateur = await db.get(Utilisateur, etape.approbateur_attendu_id)

        # Jetons : un couple actif a la fois (CDC technique 9.3). Le role decide de
        # l'action positive : un Signataire recoit "signer", jamais "approuver".
        action_positive = "signer" if etape.role == RoleEtape.SIGNATAIRE else "approuver"
        await decision_tokens.revoquer_jetons_actifs(db, etape.id)
        jeton_positif = await decision_tokens.generer_jeton_decision(
            db, etape.id, action_positive, etape.approbateur_attendu_id
        )
        jeton_refus = await decision_tokens.generer_jeton_decision(
            db, etape.id, "refuser", etape.approbateur_attendu_id
        )

        resume_budget = await suivi_budgetaire.resume_budgetaire_demande(db, demande, demandeur)
        depuis = max(0, (maintenant - _aware(etape.cree_le)).days)
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
            sujet=f"⏰ Rappel n°{etape.nombre_rappels} — décision en attente — {demandeur.nom_complet}",
            corps_html=(
                g.paragraphe("Bonjour,")
                + g.paragraphe(
                    f"Un petit rappel amical 🌟 : une {LIBELLES_PROCESSUS[demande.processus]} de "
                    f"<strong>{escape(demandeur.nom_complet)}</strong> attend votre décision depuis "
                    f"{depuis} jour(s)"
                    f"{' — ' + ', '.join(qualificatifs) if qualificatifs else ''}. "
                    "Votre réponse permet de ne pas bloquer son dossier."
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

        await audit.consigner(
            db,
            action="rappel_automatique",
            acteur_id=None,
            cible_type="etape_workflow",
            cible_id=etape.id,
            details={
                "processus": demande.processus.value,
                "numero_rappel": etape.nombre_rappels,
                "approbateur_id": str(etape.approbateur_attendu_id),
            },
        )
        await db.commit()
        return True
    except Exception:
        # Ni jetons regeneres ni rappel compte : l'ancien lien reste valable et le
        # prochain passage retentera.
        await db.rollback()
        await _restaurer(db, etape_id, precedent, nombre_avant)
        logger.exception("Echec du rappel automatique pour l'etape %s", etape_id)
        return False


async def traiter_rappels(db: AsyncSession, maintenant: datetime | None = None) -> int:
    """
    Envoie les rappels dus et retourne leur nombre. Une etape est due quand le
    dernier repere (dernier rappel, sinon creation de l'etape) remonte a plus de
    `rappel_frequence_heures`.
    """
    if not settings.rappels_automatiques_actifs or settings.rappel_frequence_heures <= 0:
        return 0
    maintenant = maintenant or datetime.now(UTC)
    seuil = maintenant - timedelta(hours=settings.rappel_frequence_heures)

    resultat = await db.execute(
        select(EtapeWorkflow.id)
        .join(Demande, Demande.id == EtapeWorkflow.demande_id)
        .join(Utilisateur, Utilisateur.id == EtapeWorkflow.approbateur_attendu_id)
        .where(
            EtapeWorkflow.statut == StatutEtape.EN_ATTENTE,
            Demande.statut_global == StatutDemande.EN_COURS,
            Utilisateur.actif.is_(True),  # inutile de relancer un compte desactive
            func.coalesce(EtapeWorkflow.dernier_rappel_le, EtapeWorkflow.cree_le) <= seuil,
        )
        .order_by(EtapeWorkflow.cree_le)
        .limit(settings.rappel_lot_max)
    )
    envoyes = 0
    for etape_id in resultat.scalars().all():
        if await _rappeler(db, etape_id, maintenant, seuil):
            envoyes += 1
    return envoyes
