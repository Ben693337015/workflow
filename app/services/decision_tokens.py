"""
Génération et vérification des jetons de décision par e-mail (section 9).

Jeton opaque aléatoire (secrets.token_urlsafe), dont seule l'empreinte
SHA-256 est stockée en base (table jetons_decision, section 4.2.5) - modèle
retenu à l'issue du benchmark de la section 9.2. JWT et itsdangerous ont été
explicitement écartés par ce benchmark : leur charge utile n'est que signée,
pas chiffrée (l'étape et l'action seraient lisibles par quiconque intercepte
le lien), et une vérification en base est de toute façon nécessaire à chaque
décision - un jeton auto-porteur n'apporte donc aucun bénéfice et ajoute une
seconde source de vérité redondante avec la ligne en base.

Écart identifié et corrigé (revue du 15/09) : ce module utilisait jusque-là
`itsdangerous.URLSafeTimedSerializer` - exactement l'option écartée par le
benchmark ci-dessus - et le jeton en clair était persisté dans un champ de
EtapeWorkflow, ce que la section 9.3 interdit explicitement ("le jeton en
clair n'est jamais persisté").

Cycle de vie complet (section 9.3) : génération -> durée de vie -> relance
(hors périmètre tant que les relances, Phase 3, ne sont pas implémentées) ->
vérification -> consommation -> purge (Phase 3, tâche #33).
"""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.jeton_decision import JetonDecision

settings = get_settings()


class JetonDecisionInvalide(ValueError):
    """Jeton inconnu, malformé, expiré ou révoqué."""


class JetonDecisionExpire(JetonDecisionInvalide):
    """Jeton valide mais dont la durée de vie est dépassée."""


class JetonDecisionRevoque(JetonDecisionInvalide):
    """Jeton valide mais explicitement révoqué (ex. remplacé par une relance)."""


class JetonDecisionDejaUtilise(JetonDecisionInvalide):
    """
    Jeton valide mais déjà consommé - distinct des autres cas d'invalidité
    (401) : il s'agit ici d'un conflit avec une décision déjà prise (409),
    pas d'un jeton qui n'a jamais été valide.
    """


def _hacher(jeton_en_clair: str) -> str:
    """SHA-256 du jeton en clair (hashlib.sha256(...).hexdigest(), section 9.3)."""
    return hashlib.sha256(jeton_en_clair.encode("utf-8")).hexdigest()


async def generer_jeton_decision(
    db: AsyncSession,
    etape_id: uuid.UUID,
    action: str,
    approbateur_attendu_id: uuid.UUID,
    duree_de_vie_heures: int | None = None,
) -> str:
    """
    Génère un jeton opaque (secrets.token_urlsafe(32)), persiste uniquement
    son empreinte, et retourne le jeton en clair - le seul moment où il
    existe, à insérer immédiatement dans l'URL de l'e-mail. Impossible à
    reconstituer depuis la base par la suite (section 9.3).
    """
    jeton_en_clair = secrets.token_urlsafe(32)
    duree = duree_de_vie_heures if duree_de_vie_heures is not None else settings.decision_token_expire_hours
    ligne = JetonDecision(
        etape_workflow_id=etape_id,
        token_hash=_hacher(jeton_en_clair),
        action_autorisee=action,
        approbateur_attendu_id=approbateur_attendu_id,
        expire_a=datetime.now(UTC) + timedelta(hours=duree),
    )
    db.add(ligne)
    await db.flush()
    return jeton_en_clair


async def verifier_et_consommer_jeton_decision(db: AsyncSession, jeton_en_clair: str) -> JetonDecision:
    """
    Vérifie le jeton (correspondance, expiration, non révoqué, non déjà
    consommé) SANS le consommer - la consommation (utilise_a) est un acte
    distinct, effectué explicitement par `consommer_jeton_decision` une fois
    toutes les autres validations métier passées (section 9.3, étape 14).
    Séparer les deux évite qu'une tentative rejetée pour une autre raison
    (ex. usurpation détectée à l'étape suivante, section 9.1) ne consomme
    par erreur le jeton légitime du véritable approbateur.

    Lève ValueError si invalide - à charge de l'appelant (route de décision)
    de traduire en réponse HTTP et de journaliser la tentative (section 9,
    tableau de sécurité "Sécurité du lien de décision").
    """
    empreinte = _hacher(jeton_en_clair)
    resultat = await db.execute(select(JetonDecision).where(JetonDecision.token_hash == empreinte))
    ligne = resultat.scalar_one_or_none()
    if ligne is None:
        raise JetonDecisionInvalide("Jeton de décision invalide ou inconnu.")
    if ligne.revoque:
        raise JetonDecisionRevoque("Jeton de décision révoqué.")
    if ligne.utilise_a is not None:
        raise JetonDecisionDejaUtilise("Jeton de décision déjà utilisé.")

    expire_a = ligne.expire_a if ligne.expire_a.tzinfo else ligne.expire_a.replace(tzinfo=UTC)
    if datetime.now(UTC) > expire_a:
        raise JetonDecisionExpire("Le jeton de décision a expiré.")

    return ligne


def consommer_jeton_decision(jeton_ligne: JetonDecision) -> None:
    """
    Marque le jeton comme consommé (section 9.3, étape 14) - à appeler dans
    la même transaction que la mise à jour de l'étape de workflow, une fois
    toutes les validations métier passées, jamais avant.
    """
    jeton_ligne.utilise_a = datetime.now(UTC)


async def revoquer_jetons_actifs(db: AsyncSession, etape_id: uuid.UUID) -> None:
    """
    Révoque tout jeton non consommé et non expiré de cette étape - à
    appeler avant d'en émettre de nouveaux (relance manuelle ou
    automatique). Garantit qu'"un seul jeton actif n'existe jamais à la
    fois sur une même étape" (§9.3).

    Écart identifié et corrigé (revue du 16/09), suite au test réel de
    bout en bout : la relance manuelle n'existait pas du tout - un e-mail
    de décision resté sans réponse (ou jamais délivré) n'avait aucun
    moyen de rattrapage côté interface.
    """
    resultat = await db.execute(
        select(JetonDecision).where(
            JetonDecision.etape_workflow_id == etape_id,
            JetonDecision.utilise_a.is_(None),
            JetonDecision.revoque.is_(False),
        )
    )
    for ligne in resultat.scalars().all():
        ligne.revoque = True
