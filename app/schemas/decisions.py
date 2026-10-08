"""Schemas de la route de decision par lien e-mail (section 9)."""
from pydantic import BaseModel

from app.schemas.pieces_jointes import PieceJointeRead


class DecisionRequest(BaseModel):
    # Obligatoire en cas de refus (section 2.3 du CDC fonctionnel : un refus
    # sans motif écrit ne doit pas pouvoir clore le dossier), verifie dans
    # le routeur car cela depend de l'action encodee dans le jeton, pas d'un
    # champ du formulaire.
    commentaire: str | None = None
    # Ecart identifie et corrige (revue du 27/09) : le role Signataire
    # (section 8 - "Capturer une signature a l'ecran, ou refuser") etait
    # jusqu'ici traite comme un simple Approbateur, sans rien capturer.
    # Image PNG du trace de signature (dessine sur un canvas cote client),
    # encodee en base64 - obligatoire uniquement pour l'action "signer",
    # verifie dans le routeur car cela depend elle aussi de l'action encodee
    # dans le jeton, pas d'un champ toujours requis du formulaire.
    signature_image_base64: str | None = None
    # Ecart n°4 (section 4.4 du CDC fonctionnel) : "une justification
    # d'acceptation par l'arbitre" est obligatoire pour approuver une etape
    # d'arbitrage exceptionnel (etape.est_derogation) - jamais pour un
    # refus (refuser une derogation n'a pas besoin d'etre justifie au-dela
    # du commentaire deja obligatoire), ni pour une decision ordinaire.
    justification_acceptation: str | None = None


class DecisionResponse(BaseModel):
    demande_id: str
    etape_id: str
    action: str
    statut_global: str


class BudgetApercu(BaseModel):
    """Situation budgetaire du service du demandeur (CDC 4.3) - notes de frais et achats uniquement."""
    service: str
    exercice: int
    solde_disponible: float
    montant_demande: float
    solde_apres_validation: float
    devise: str = "EUR"  # devise de reference, celle des enveloppes


class ApercuDecision(BaseModel):
    """
    Prevue en lecture seule d'un jeton de decision, avant toute soumission -
    permet au frontend de savoir quel formulaire afficher (signature,
    justification de derogation) sans deviner. Ne consomme jamais le jeton.
    """
    action: str
    processus: str
    est_derogation: bool
    # Necessaires a l'interface de discussion (ecart n°5, section 4.5) : les
    # routes /demandes/{id}/suspendre|messages|reprendre sont indexees par
    # l'identifiant de la demande, et la page de decision doit savoir si une
    # discussion est deja ouverte (statut "complement_demande").
    demande_id: str
    statut_demande: str
    demandeur_nom: str
    resume: dict
    # Solde budgetaire a montrer au decideur : renseigne pour les notes de frais
    # et les achats, None pour les conges (pas d'enveloppe budgetaire).
    budget: BudgetApercu | None = None
    # Pieces du dossier (recu, justificatif, contrat, complements) : l'approbateur doit pouvoir les
    # consulter depuis la page de decision. Noms seulement ici ; le telechargement exige une session.
    pieces_jointes: list[PieceJointeRead] = []
