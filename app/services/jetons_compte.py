"""
Invitation et réinitialisation de mot de passe (section 5 du CDC technique).

Même mécanisme que les jetons de décision (section 9.2-9.3, app/services/
decision_tokens.py) : jeton opaque (secrets.token_urlsafe), seule son
empreinte SHA-256 est persistée. Réutilisé ici pour deux usages :

- INVITATION : à la création d'un compte par le DRH (aucun mot de passe
  choisi par le DRH - écart corrigé, revue du 15/09).
- REINITIALISATION : mot de passe oublié (exigence explicite du CDC, §5,
  jusqu'ici non implémentée).
"""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TypeJetonCompte
from app.models.jeton_compte import JetonCompte

DUREE_INVITATION_HEURES = 7 * 24  # 7 jours - le temps de rejoindre à son rythme
DUREE_REINITIALISATION_HEURES = 2  # court, comme toute reinitialisation de mot de passe


class JetonCompteInvalide(ValueError):
    """Jeton de compte inconnu, expiré, révoqué ou déjà utilisé."""


def _hacher(jeton_en_clair: str) -> str:
    return hashlib.sha256(jeton_en_clair.encode("utf-8")).hexdigest()


async def generer_jeton_compte(db: AsyncSession, utilisateur_id: uuid.UUID, type_jeton: TypeJetonCompte) -> str:
    """Génère un jeton opaque, persiste uniquement son empreinte, retourne le jeton en clair."""
    duree = DUREE_INVITATION_HEURES if type_jeton == TypeJetonCompte.INVITATION else DUREE_REINITIALISATION_HEURES
    jeton_en_clair = secrets.token_urlsafe(32)
    ligne = JetonCompte(
        utilisateur_id=utilisateur_id,
        token_hash=_hacher(jeton_en_clair),
        type_jeton=type_jeton,
        expire_a=datetime.now(UTC) + timedelta(hours=duree),
    )
    db.add(ligne)
    await db.flush()
    return jeton_en_clair


async def verifier_et_consommer_jeton_compte(db: AsyncSession, jeton_en_clair: str) -> JetonCompte:
    """
    Vérifie le jeton et le consomme immédiatement (utilise_a) - à la
    différence des jetons de décision, il n'y a ici aucune validation métier
    intermédiaire susceptible d'échouer après coup : consommer dès la
    vérification est donc sûr et évite un aller-retour supplémentaire.
    """
    empreinte = _hacher(jeton_en_clair)
    resultat = await db.execute(select(JetonCompte).where(JetonCompte.token_hash == empreinte))
    ligne = resultat.scalar_one_or_none()
    if ligne is None:
        raise JetonCompteInvalide("Jeton invalide ou inconnu.")
    if ligne.revoque:
        raise JetonCompteInvalide("Ce lien a été révoqué (une invitation plus récente a été envoyée).")
    if ligne.utilise_a is not None:
        raise JetonCompteInvalide("Ce lien a déjà été utilisé.")

    expire_a = ligne.expire_a if ligne.expire_a.tzinfo else ligne.expire_a.replace(tzinfo=UTC)
    if datetime.now(UTC) > expire_a:
        raise JetonCompteInvalide("Ce lien a expiré.")

    ligne.utilise_a = datetime.now(UTC)
    return ligne


async def revoquer_jetons_actifs(db: AsyncSession, utilisateur_id: uuid.UUID, type_jeton: TypeJetonCompte) -> None:
    """
    Révoque tout jeton non consommé et non expiré du type demandé pour cet
    utilisateur - à appeler avant d'en émettre un nouveau (renvoi
    d'invitation, nouvelle demande de réinitialisation), pour qu'un seul
    lien reste valide à la fois (même principe que les jetons de décision,
    §9.3 : "un seul jeton actif n'existe jamais à la fois sur une même
    étape").

    Écart identifié et corrigé (revue du 16/09), suite au test réel de bout
    en bout : sans renvoi possible, un jeton perdu (e-mail non délivré)
    n'avait aucune solution de rattrapage côté interface.
    """
    resultat = await db.execute(
        select(JetonCompte).where(
            JetonCompte.utilisateur_id == utilisateur_id,
            JetonCompte.type_jeton == type_jeton,
            JetonCompte.utilise_a.is_(None),
            JetonCompte.revoque.is_(False),
        )
    )
    for ligne in resultat.scalars().all():
        ligne.revoque = True
