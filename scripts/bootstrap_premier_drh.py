"""
Bootstrap du tout premier compte DRH sur un déploiement neuf.

Écart identifié (revue du 16/09) : sans ce script, il n'existe AUCUN moyen
de créer le premier compte de la plateforme. Depuis le retrait de
l'auto-inscription (choix assumé, section 5 : la création de compte est un
acte RH, pas une inscription libre), `POST /api/v1/utilisateurs/` exige
déjà d'être authentifié en tant que DRH - un blocage de type "œuf et
poule" sur toute base fraîchement migrée. `scripts/seed_demo.py` ne
convient pas à cet usage : il crée un jeu de données de démonstration
complet avec des mots de passe codés en dur, pensé pour le développement
local.

Ce script, à l'inverse :
  - ne crée QU'UN seul compte (le DRH), sans données de démonstration ;
  - ne fixe jamais de mot de passe en clair - il réutilise le mécanisme
    d'invitation déjà en place (section 5, JetonCompte) : le lien
    d'activation est envoyé par e-mail si Resend est configuré, et affiché
    dans la console dans tous les cas (utile en développement, ou si
    l'envoi échoue) ;
  - refuse de s'exécuter si un DRH existe déjà (idempotent par défaut),
    sauf option --force explicite, pour éviter un usage accidentel en
    production après la mise en service.

Usage :
    cd plateforme-workflows
    python3 scripts/bootstrap_premier_drh.py --email drh@organisation.tld --nom "Prénom Nom" --service RH

Variables d'environnement équivalentes (utile pour un déploiement scripté /
conteneurisé sans argument interactif) :
    BOOTSTRAP_DRH_EMAIL, BOOTSTRAP_DRH_NOM, BOOTSTRAP_DRH_SERVICE
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.enums import RoleUtilisateur, TypeJetonCompte  # noqa: E402
from app.models.user import Utilisateur  # noqa: E402
from app.services import email_service, jetons_compte  # noqa: E402

settings = get_settings()


def _lire_arguments() -> argparse.Namespace:
    parseur = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parseur.add_argument("--email", default=os.environ.get("BOOTSTRAP_DRH_EMAIL"), help="E-mail du premier compte DRH")
    parseur.add_argument("--nom", default=os.environ.get("BOOTSTRAP_DRH_NOM"), help="Nom complet")
    parseur.add_argument(
        "--service", default=os.environ.get("BOOTSTRAP_DRH_SERVICE", "RH"), help="Service (défaut : RH)"
    )
    parseur.add_argument(
        "--force",
        action="store_true",
        help="Créer ce compte même si un DRH existe déjà (déconseillé après la mise en service)",
    )
    return parseur.parse_args()


async def bootstrap(email: str, nom_complet: str, service: str, force: bool) -> None:
    async with AsyncSessionLocal() as db:
        resultat_drh_existant = await db.execute(
            select(Utilisateur).where(Utilisateur.role == RoleUtilisateur.DRH, Utilisateur.actif.is_(True))
        )
        drh_existants = resultat_drh_existant.scalars().all()
        if drh_existants and not force:
            print(
                f"[Annulé] {len(drh_existants)} compte(s) DRH actif(s) existe(nt) déjà "
                f"({', '.join(d.email for d in drh_existants)}). "
                "Utilisez le compte DRH existant pour inviter de nouveaux comptes via l'interface, "
                "ou relancez avec --force si vous savez ce que vous faites.",
                file=sys.stderr,
            )
            sys.exit(1)

        resultat_email = await db.execute(select(Utilisateur).where(Utilisateur.email == email))
        if resultat_email.scalar_one_or_none() is not None:
            print(f"[Annulé] Un compte existe déjà avec l'e-mail {email}.", file=sys.stderr)
            sys.exit(1)

        # Meme principe que la creation de compte par le DRH (section 5) :
        # aucun mot de passe fixe ici, meme pour ce tout premier compte.
        drh = Utilisateur(
            email=email,
            mot_de_passe_hash=None,
            nom_complet=nom_complet,
            service=service,
            role=RoleUtilisateur.DRH,
        )
        db.add(drh)
        await db.flush()

        jeton = await jetons_compte.generer_jeton_compte(db, drh.id, TypeJetonCompte.INVITATION)
        await db.commit()

        lien_activation = f"{settings.frontend_base_url}/activer-compte/{jeton}"

        print("Compte DRH créé avec succès :")
        print(f"  E-mail        : {email}")
        print(f"  Nom complet   : {nom_complet}")
        print(f"  Service       : {service}")
        print(f"  Lien d'activation (usage unique, valable 7 jours) :\n    {lien_activation}")

        try:
            await email_service.envoyer_email(
                destinataire=email,
                sujet="Activation de votre compte DRH — Plateforme Workflows",
                corps_html=(
                    f"<p>Un compte DRH vous a été créé sur la plateforme d'approbation de workflows.</p>"
                    f"<p><a href='{lien_activation}'>Cliquez ici pour définir votre mot de passe et "
                    f"activer votre compte</a> (lien valable 7 jours).</p>"
                ),
            )
            print("  E-mail d'invitation envoyé avec succès via Resend.")
        except Exception as exc:
            print(
                f"  [Avertissement] L'e-mail n'a pas pu être envoyé ({exc}). "
                "Communiquez le lien d'activation ci-dessus par un autre canal sécurisé.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    args = _lire_arguments()
    if not args.email or not args.nom:
        print("Usage : python3 scripts/bootstrap_premier_drh.py --email ... --nom \"...\" [--service RH]", file=sys.stderr)
        sys.exit(2)
    asyncio.run(bootstrap(args.email, args.nom, args.service, args.force))
