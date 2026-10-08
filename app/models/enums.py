"""Enumerations partagees par les modeles (section 4, 7 et 8 du CDC technique)."""
import enum


class TypeProcessus(str, enum.Enum):
    CONGES = "conges"
    NOTES_FRAIS = "notes_frais"
    ACHATS = "achats"


class RoleUtilisateur(str, enum.Enum):
    EMPLOYE = "employe"
    MANAGER = "manager"
    DRH = "drh"
    DIRECTION_FINANCIERE = "direction_financiere"
    SERVICE_JURIDIQUE = "service_juridique"
    DIRECTION_GENERALE = "direction_generale"
    CONTROLEUR_DE_GESTION = "controleur_de_gestion"


class RoleEtape(str, enum.Enum):
    """Sept roles de destinataire (section 8)."""
    APPROBATEUR = "approbateur"
    SIGNATAIRE = "signataire"
    DESTINATAIRE_COPIE = "destinataire_copie"
    RECOMMANDEUR = "recommandeur"
    ACCUSE_RECEPTION = "accuse_reception"
    EXECUTANT_TACHE = "executant_tache"
    EDITEUR = "editeur"


class StatutEtape(str, enum.Enum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    APPROUVE = "approuve"
    REFUSE = "refuse"


class StatutDemande(str, enum.Enum):
    EN_COURS = "en_cours"
    TERMINEE = "terminee"
    REFUSEE = "refusee"
    COMPLEMENT_DEMANDE = "complement_demande"
    ANNULEE = "annulee"


class EvenementWebhook(str, enum.Enum):
    """Catalogue d'evenements (section 10)."""
    DEMANDE_SOUMISE = "demande_soumise"
    ETAPE_APPROUVEE = "etape_approuvee"
    ETAPE_REFUSEE = "etape_refusee"
    COMPLEMENT_DEMANDE = "complement_demande"
    CIRCUIT_TERMINE = "circuit_termine"
    DEMANDE_ANNULEE = "demande_annulee"
    DEROGATION_DECLENCHEE = "derogation_declenchee"


class TypeJetonCompte(str, enum.Enum):
    """
    Ecart identifie et corrige (revue du 15/09) : le CDC (section 5) exige un
    mecanisme de reinitialisation par e-mail, avec un lien a usage unique et
    a expiration courte, construit sur le meme mecanisme cryptographique que
    les liens de decision (section 9) - inexistant jusqu'ici. Meme table,
    meme mecanisme (jeton opaque + hash), pour deux usages distincts :
    l'invitation initiale (le DRH cree le compte SANS mot de passe) et la
    reinitialisation en cas d'oubli.
    """
    INVITATION = "invitation"
    REINITIALISATION = "reinitialisation"


class MotifMouvementConges(str, enum.Enum):
    """
    Motif d'une ecriture sur le solde de conges (CDC technique 4.2.7 et 11.1.1).

    Regle : toute variation du solde disponible passe par un mouvement, jamais par
    une mise a jour directe et muette. Les six premiers motifs sont ceux du CDC ;
    `liberation_modification` a ete ajoute pour la modification d'une demande en
    cours (l'ancienne reservation est liberee avant d'en creer une nouvelle).
    """

    SOLDE_INITIAL = "solde_initial"
    ACQUISITION_MENSUELLE = "acquisition_mensuelle"
    RESERVATION = "reservation"
    LIBERATION_REFUS = "liberation_refus"
    LIBERATION_ANNULATION = "liberation_annulation"
    LIBERATION_MODIFICATION = "liberation_modification"
    AJUSTEMENT_MANUEL = "ajustement_manuel"
