"""
Journalisation d'audit (section 4 / 14.3) : ecriture seule (append-only).

Chaque action (soumission, decision, relance, derogation, message de
clarification, operation d'administration) est consignee avec horodatage
exact et identifiant de l'auteur. `consigner` ne fait qu'ajouter une ligne ;
l'inalterabilite (CDC 2.4, technique 14.3) est imposee par la base : voir
app/models/journal_audit.py (declencheurs) et scripts/roles_postgresql.sql
(role applicatif sans droit de modification).

Consultation (ecart trouve par l'audit de conformite du 28/09 : aucune route ne
lisait le journal) : `rechercher` pour les roles de controle, `historique_demande`
pour les participants d'un dossier.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demande import Demande
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur
from app.schemas.audit import AuditEntree, HistoriqueEntree

LIBELLES = {
    # Circuit de validation
    "demande_soumise": "Demande soumise",
    "etape_approuvee": "Étape approuvée",
    "etape_signee": "Étape signée",
    "etape_refusee": "Étape refusée",
    "demande_annulee": "Demande annulée",
    "demande_modifiee": "Demande modifiée",
    "demande_regularisee": "Demande régularisée",
    "decision_relancee": "Relance manuelle",
    "rappel_automatique": "Rappel automatique",
    "piece_jointe_ajoutee": "Pièce jointe ajoutée",
    # Discussion (écart n°5)
    "demande_suspendue_precisions": "Précisions demandées (décision suspendue)",
    "message_clarification_envoye": "Message dans la discussion",
    "demande_reprise_apres_precisions": "Workflow repris",
    # Sécurité
    "tentative_jeton_invalide": "Tentative avec un lien de décision invalide",
    "tentative_decision_usurpation": "Tentative de décision par un autre utilisateur",
    "connexion_reussie": "Connexion réussie",
    "connexion_echouee": "Tentative de connexion échouée",
    "compte_verrouille": "Compte verrouillé (trop de tentatives de connexion)",
    # Administration
    "compte_cree": "Compte créé",
    "compte_invitation_renvoyee": "Invitation renvoyée",
    "compte_modifie": "Compte modifié",
    "compte_desactive": "Compte désactivé",
    "compte_reactive": "Compte réactivé",
    "solde_conges_defini": "Solde de congés défini",
    "enveloppe_budgetaire_definie": "Enveloppe budgétaire définie",
    "type_conge_cree": "Type de congé créé",
    "type_conge_desactive": "Type de congé désactivé",
    "type_conge_reactive": "Type de congé réactivé",
    "jour_ferie_cree": "Jour férié créé",
    "taux_change_defini": "Taux de change défini",
    "synthese_comptabilite_envoyee": "Synthèse transmise à la comptabilité",
    "synthese_frais_exportee": "Synthèse des notes de frais exportée",
}


def libelle(action: str) -> str:
    return LIBELLES.get(action, action)


async def consigner(
    db: AsyncSession,
    action: str,
    acteur_id: uuid.UUID | None,
    cible_type: str,
    cible_id: uuid.UUID | None,
    details: dict,
) -> JournalAudit:
    """Ajoute une entree au journal d'audit (ne commit pas : a la charge de l'appelant)."""
    entree = JournalAudit(
        action=action,
        acteur_id=acteur_id,
        cible_type=cible_type,
        cible_id=cible_id,
        details=details,
    )
    db.add(entree)
    await db.flush()
    return entree


def _en_utc(valeur: datetime) -> datetime:
    return valeur.astimezone(UTC) if valeur.tzinfo else valeur.replace(tzinfo=UTC)


async def _noms(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    resultat = await db.execute(select(Utilisateur.id, Utilisateur.nom_complet).where(Utilisateur.id.in_(ids)))
    return {i: n for i, n in resultat.all()}


async def rechercher(
    db: AsyncSession,
    *,
    action: str | None = None,
    acteur_id: uuid.UUID | None = None,
    cible_type: str | None = None,
    cible_id: uuid.UUID | None = None,
    depuis: datetime | None = None,
    jusqu_a: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[AuditEntree]]:
    """Journal filtre, du plus recent au plus ancien ; retourne (total, page)."""
    conditions = []
    if action:
        conditions.append(JournalAudit.action == action)
    if acteur_id:
        conditions.append(JournalAudit.acteur_id == acteur_id)
    if cible_type:
        conditions.append(JournalAudit.cible_type == cible_type)
    if cible_id:
        conditions.append(JournalAudit.cible_id == cible_id)
    if depuis:
        conditions.append(JournalAudit.horodate_le >= _en_utc(depuis))
    if jusqu_a:
        conditions.append(JournalAudit.horodate_le <= _en_utc(jusqu_a))

    total = await db.scalar(select(func.count()).select_from(JournalAudit).where(*conditions))
    lignes = (
        await db.execute(
            select(JournalAudit)
            .where(*conditions)
            .order_by(JournalAudit.horodate_le.desc(), JournalAudit.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    noms = await _noms(db, {l.acteur_id for l in lignes if l.acteur_id})
    return total or 0, [
        AuditEntree(
            id=str(l.id),
            action=l.action,
            libelle=libelle(l.action),
            acteur_id=str(l.acteur_id) if l.acteur_id else None,
            acteur_nom=noms.get(l.acteur_id, "Utilisateur inconnu") if l.acteur_id else "Système",
            cible_type=l.cible_type,
            cible_id=str(l.cible_id) if l.cible_id else None,
            details=l.details,
            horodate_le=_en_utc(l.horodate_le).isoformat(),
        )
        for l in lignes
    ]


def _detail_lisible(action: str, details: dict) -> str | None:
    """
    Resume court d'une entree pour le dossier. Volontairement restreint : le contenu des
    messages de discussion n'est pas repris (il a sa propre route, avec ses propres regles).
    """
    if action in ("etape_approuvee", "etape_signee", "etape_refusee"):
        morceaux = []
        if details.get("commentaire"):
            morceaux.append(f"Commentaire : {details['commentaire']}")
        if details.get("justification_acceptation"):
            morceaux.append(f"Justification d'acceptation : {details['justification_acceptation']}")
        return " — ".join(morceaux) or None
    if action == "demande_soumise" and details.get("motif_derogation"):
        return f"Dérogation demandée : {details['motif_derogation']}"
    if action == "piece_jointe_ajoutee" and details.get("fichier"):
        return details["fichier"]
    if action == "rappel_automatique" and details.get("numero_rappel"):
        return f"Rappel n°{details['numero_rappel']}"
    return None


async def historique_demande(db: AsyncSession, demande: Demande) -> list[HistoriqueEntree]:
    """Chronologie d'un dossier : ses entrees propres et celles de ses etapes, de la plus ancienne a la plus recente."""
    etapes = (await db.execute(select(EtapeWorkflow.id).where(EtapeWorkflow.demande_id == demande.id))).scalars().all()
    lignes = (
        await db.execute(
            select(JournalAudit)
            .where(
                ((JournalAudit.cible_type == "demande") & (JournalAudit.cible_id == demande.id))
                | ((JournalAudit.cible_type == "etape_workflow") & (JournalAudit.cible_id.in_(etapes or [uuid.uuid4()])))
            )
            .order_by(JournalAudit.horodate_le, JournalAudit.id)
        )
    ).scalars().all()
    noms = await _noms(db, {l.acteur_id for l in lignes if l.acteur_id})
    return [
        HistoriqueEntree(
            horodate_le=_en_utc(l.horodate_le).isoformat(),
            action=l.action,
            libelle=libelle(l.action),
            acteur_nom=noms.get(l.acteur_id, "Utilisateur inconnu") if l.acteur_id else "Système",
            detail=_detail_lisible(l.action, l.details or {}),
        )
        for l in lignes
    ]
