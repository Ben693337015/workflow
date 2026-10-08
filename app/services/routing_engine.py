"""
Moteur de routage (section 7 du CDC technique).

Mecanismes complets attendus a terme : destinataire statique, destinataire
dynamique, destinataire de groupe (unanime / majoritaire), ordre de reception
(niveaux paralleles ou sequentiels), et logique conditionnelle (ET / OU).

Implemente a ce jour :
- Conges : destinataire dynamique = manager direct du demandeur, un seul
  niveau (determiner_etape_suivante renvoie toujours None : l'approbation
  du manager termine le circuit).
- Notes de frais : meme premier niveau (manager direct), puis logique
  conditionnelle (section 7) sur le montant - au-dela du seuil configure
  (Settings.notes_frais_seuil_direction_financiere), un second niveau est
  ajoute vers un compte actif de role Direction financiere.
- Achats : circuit fixe a deux niveaux, sans manager (CDC section 3) -
  premier niveau vers un compte actif de role Service juridique (avis),
  puis toujours un second niveau vers un compte actif de role Direction
  generale (role Signataire, section 8 - la capture d'une signature
  graphique elle-meme reste hors perimetre, voir app/routers/decisions.py).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.demande import Demande
from app.models.enums import RoleEtape, RoleUtilisateur, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.services import devises

settings = get_settings()


async def _premier_compte_actif(db: AsyncSession, role: RoleUtilisateur) -> Utilisateur | None:
    resultat = await db.execute(
        select(Utilisateur).where(Utilisateur.role == role, Utilisateur.actif.is_(True))
    )
    return resultat.scalars().first()


async def determiner_premiere_etape(
    db: AsyncSession, demande: Demande, demandeur: Utilisateur
) -> EtapeWorkflow:
    """Calcule la premiere etape de workflow selon le type de processus."""
    if demande.processus in (TypeProcessus.CONGES, TypeProcessus.NOTES_FRAIS):
        if demandeur.manager_id is None:
            raise ValueError(
                "Aucun manager rattache a cet utilisateur : impossible de router la demande."
            )
        return EtapeWorkflow(
            demande_id=demande.id,
            niveau=1,
            role=RoleEtape.APPROBATEUR,
            approbateur_attendu_id=demandeur.manager_id,
        )

    if demande.processus == TypeProcessus.ACHATS:
        juriste = await _premier_compte_actif(db, RoleUtilisateur.SERVICE_JURIDIQUE)
        if juriste is None:
            raise ValueError(
                "Aucun compte actif de rôle Service juridique : impossible de router cette demande d'achat."
            )
        return EtapeWorkflow(
            demande_id=demande.id,
            niveau=1,
            role=RoleEtape.APPROBATEUR,
            approbateur_attendu_id=juriste.id,
        )

    raise NotImplementedError(
        f"Routage non implemente pour le processus '{demande.processus.value}'."
    )


async def determiner_etape_derogation(db: AsyncSession, demande: Demande) -> EtapeWorkflow:
    """
    Ecart n°4 (section 4.4 du CDC fonctionnel) : circuit d'arbitrage
    exceptionnel, en detournement complet du circuit standard (pas un
    niveau ajoute apres coup, contrairement a l'escalade de niveau 2 des
    notes de frais/achats) - "le flux doit etre immediatement detourne de
    sa trajectoire habituelle". Un seul niveau, vers une instance
    d'arbitrage superieure :
    - NOTES DE FRAIS : Direction financiere uniquement (decision du 07/10) ;
    - ACHATS : Controleur de gestion en priorite (l'arbitre le plus directement
      concerne par un depassement budgetaire), Direction generale en repli si
      aucun compte actif de ce role n'existe.
    """
    if demande.processus == TypeProcessus.NOTES_FRAIS:
        # Decision du 07/10 : une note de frais en derogation (budget depasse ou motif du demandeur) est
        # arbitree par la DIRECTION FINANCIERE seule - ni Controleur de gestion, ni repli sur la Direction
        # generale. Sans compte actif de ce role, la soumission echoue clairement.
        arbitre = await _premier_compte_actif(db, RoleUtilisateur.DIRECTION_FINANCIERE)
        if arbitre is None:
            raise ValueError(
                "Aucun compte actif de rôle Direction financière : impossible de router cette note de frais "
                "vers l'arbitrage exceptionnel."
            )
    else:
        arbitre = await _premier_compte_actif(db, RoleUtilisateur.CONTROLEUR_DE_GESTION)
        if arbitre is None:
            arbitre = await _premier_compte_actif(db, RoleUtilisateur.DIRECTION_GENERALE)
        if arbitre is None:
            raise ValueError(
                "Aucun compte actif de rôle Contrôleur de gestion ou Direction générale : "
                "impossible de router cette demande vers l'arbitrage exceptionnel."
            )
    return EtapeWorkflow(
        demande_id=demande.id,
        niveau=1,
        role=RoleEtape.APPROBATEUR,
        approbateur_attendu_id=arbitre.id,
        est_derogation=True,
    )


async def determiner_etape_suivante(
    db: AsyncSession, demande: Demande, etape_actuelle: EtapeWorkflow
) -> EtapeWorkflow | None:
    """
    Calcule l'etape suivante apres l'approbation de `etape_actuelle`, ou
    None si le circuit doit se terminer (derniere etape approuvee).

    Ne s'applique qu'a une etape APPROUVEE : un refus termine toujours le
    circuit immediatement (section 7), quel que soit le processus - ce
    choix est fait par l'appelant (app/routers/decisions.py), pas ici.
    """
    if demande.processus == TypeProcessus.CONGES:
        # Un seul niveau (le manager) : toujours la derniere etape.
        return None

    if demande.processus == TypeProcessus.NOTES_FRAIS:
        if etape_actuelle.est_derogation:
            # Circuit d'arbitrage exceptionnel (section 4.4) : une seule
            # etape, quel que soit le montant - l'arbitre a deja tranche.
            return None
        if etape_actuelle.niveau >= 2:
            # Deuxieme niveau (Direction financiere) deja franchi : fin.
            return None

        # Le seuil est exprime dans la devise de reference : on compare le montant CONVERTI (fige a la
        # soumission), jamais le montant brut - 500 XAF ne sont pas 500 EUR.
        montant = devises.montant_reference(demande.donnees, "montant")
        if montant <= settings.notes_frais_seuil_direction_financiere:
            # Sous le seuil : l'approbation du manager suffit.
            return None

        # Au-dela du seuil (section 7, logique conditionnelle) : un second
        # niveau est ajoute vers un compte actif de role Direction financiere.
        approbateur = await _premier_compte_actif(db, RoleUtilisateur.DIRECTION_FINANCIERE)
        if approbateur is None:
            raise ValueError(
                "Aucun compte actif de rôle Direction financière : impossible de "
                "router cette note de frais au-delà du seuil configuré."
            )
        return EtapeWorkflow(
            demande_id=demande.id,
            niveau=2,
            role=RoleEtape.APPROBATEUR,
            approbateur_attendu_id=approbateur.id,
        )

    if demande.processus == TypeProcessus.ACHATS:
        if etape_actuelle.est_derogation:
            # Circuit d'arbitrage exceptionnel (section 4.4) : une seule
            # etape - l'arbitre a deja tranche, pas de passage par le
            # juridique ou la Direction generale ensuite.
            return None
        if etape_actuelle.niveau >= 2:
            # Direction generale (signataire) deja franchie : fin du circuit.
            return None

        # Circuit fixe (pas de logique conditionnelle) : l'avis juridique
        # est toujours suivi de la signature de la Direction generale.
        signataire = await _premier_compte_actif(db, RoleUtilisateur.DIRECTION_GENERALE)
        if signataire is None:
            raise ValueError(
                "Aucun compte actif de rôle Direction générale : impossible de "
                "router cette demande d'achat vers la signature finale."
            )
        return EtapeWorkflow(
            demande_id=demande.id,
            niveau=2,
            role=RoleEtape.SIGNATAIRE,
            approbateur_attendu_id=signataire.id,
        )

    raise NotImplementedError(
        f"Routage non implemente pour le processus '{demande.processus.value}'."
    )
