"""
Configuration centralisee de l'application.

Correspond au principe de la section 3.2 du CDC technique : le backend lit sa
configuration depuis l'environnement (variables .env), jamais en dur dans le
code. Voir .env.example pour la liste complete des variables attendues.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Plateforme d'approbation de workflows"
    environment: str = "development"
    secret_key: str

    # Base de donnees
    database_url: str

    # JWT (section 5)
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 45
    refresh_token_expire_days: int = 14

    # Jetons de decision (section 9)
    # Ecart corrige (revue du 15/09) : `decision_token_secret` a ete retire -
    # il servait a signer les jetons via itsdangerous (mecanisme ecarte par
    # le benchmark de la section 9.2). Le jeton opaque retenu (section 9.3)
    # ne repose sur aucun secret : sa securite vient de son entropie
    # (secrets.token_urlsafe) et de son empreinte stockee en base.
    # Duree de vie par defaut alignee sur la section 9.3 (14 jours glissants,
    # calee sur le rythme des relances a 48h) plutot que sur une valeur
    # arbitraire plus courte.
    decision_token_expire_hours: int = 14 * 24

    # Rappels automatiques (CDC fonctionnel 2.4 : "relance automatique des
    # dossiers en attente selon une frequence parametrable (ex. toutes les 48
    # heures)"). Aucun mecanisme de ce type n'existait avant l'audit de
    # conformite du 28/09 - seule la relance manuelle des conges.
    rappels_automatiques_actifs: bool = True
    rappel_frequence_heures: float = 48.0  # <= 0 desactive les rappels
    rappel_verification_minutes: float = 15.0  # periodicite du controle
    rappel_lot_max: int = 200  # dossiers traites au plus par passage
    decision_requires_active_session: bool = True

    # Webhooks (section 10)
    webhook_max_retries: int = 5

    # E-mail (section 14.2 - Resend)
    resend_api_key: str = ""
    email_from: str = "Plateforme Workflows <notifications@example.com>"

    # URL publique du frontend (page de décision /decisions/:jeton, section 9).
    # Ecart identifié : les liens de décision envoyés par e-mail pointaient
    # vers un domaine factice codé en dur ("exemple.tld") - corrigé pour
    # utiliser cette valeur configurable.
    frontend_base_url: str = "http://localhost:3000"

    # Stockage fichiers (NubieS3 / S3 compatible) : actif si les 4 variables S3_* sont renseignees, sinon dossier local.
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # Region du bucket (ex. eu-central-003) : vide = deduite de l'endpoint (s3.<region>.<domaine>).
    s3_region: str = ""
    # Prefixe (« dossier ») dans le bucket : utile quand le bucket est partage avec d'autres applications.
    s3_prefix: str = "workflows/"

    # Regles metier
    conges_report_solde_illimite: bool = True
    # R9 : limitation des connexions echouees (CDC 5). Apres N echecs consecutifs, le compte est verrouille.
    connexion_max_tentatives: int = 5
    connexion_duree_verrouillage_minutes: int = 15
    # R22 : cle Fernet du chiffrement au repos des secrets webhook. Vide : derivee de SECRET_KEY.
    webhook_encryption_key: str = ""
    conges_unite_jour_entier: bool = True
    # R20 : la duree d'un conge est comptee en jours CALENDAIRES (week-ends inclus) tant que la DRH
    # n'a pas valide une regle differente. Passer a true pour ne compter que du lundi au vendredi.
    conges_exclure_weekends: bool = False
    # Devise de REFERENCE : celle des enveloppes budgetaires, des soldes et du seuil ci-dessous. Toute
    # demande dans une autre devise est convertie a la soumission (taux de change, decision du 28/09).
    # Si vous changez la devise de reference, adaptez aussi le seuil (500 EUR ~ 328 000 XAF).
    devise_reference: str = "EUR"
    notes_frais_seuil_direction_financiere: float = 500.00  # exprime dans la devise de reference

    # Synthese des notes de frais validees transmise a la comptabilite (CDC fonctionnel 3 : "tableau
    # de synthese des frais valides transmis a la comptabilite pour remboursement"). Vide : aucun
    # e-mail n'est envoye (l'ecran de synthese reste disponible).
    comptabilite_email: str = ""
    # Taux de TVA utilise pour la ventilation HT/TVA/TTC du bon de commande
    # (ecart n°1, section 4.1 du CDC technique) - hypothese assumee : le CDC
    # ne precise pas de taux, 20% est le taux normal francais le plus courant.
    taux_tva_bon_de_commande: float = 0.20
    # Dossier de stockage local des pieces jointes : utilise UNIQUEMENT quand les variables S3_* sont vides
    # (developpement, tests) - voir app/services/stockage_fichiers.py. Avec S3 actif, il n'est pas utilise.
    stockage_fichiers_dossier: str = "/var/lib/workflows/pieces-jointes"

    # CORS (necessaire si un navigateur appelle l'API directement depuis
    # une autre origine). Depuis le passage du frontend a Next.js, les
    # appels transitent par un proxy cote serveur (voir
    # frontend/src/app/api/backend/[...path]/route.ts) : le navigateur
    # n'appelle plus jamais directement cette API en cross-origin, ce qui
    # rend ce reglage surtout defensif (appel direct depuis un outil externe,
    # tests manuels...) plutot que strictement necessaire au fonctionnement
    # normal de l'application.
    cors_allow_origins: str = "http://localhost:3000"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origine.strip() for origine in self.cors_allow_origins.split(",") if origine.strip()]


@lru_cache
def get_settings() -> Settings:
    """Instancie les settings une seule fois (mise en cache)."""
    return Settings()
