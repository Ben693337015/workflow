"""
Test d'envoi RÉEL via Resend, avec une vraie clé API.

Ce script ne peut PAS être exécuté par Claude : le réseau du bac à sable où
le code a été développé est restreint à une liste fixe de domaines
(PyPI, npm, GitHub...) qui n'inclut pas api.resend.com. Il est fait pour
être lancé par vous, dans votre propre environnement (poste local, serveur
de dev), avec de vrais identifiants.

Ce script utilise directement app.services.email_service (le vrai code de
l'application, pas un mock) - un envoi réussi ici confirme que
l'intégration Resend fonctionne réellement en conditions réelles.

Prérequis (section 14.2.1 du CDC) :
  - Un compte Resend et une clé API valide.
  - SOIT un domaine d'envoi vérifié dans Resend (recommandé, DNS SPF/DKIM
    publiés) : vous pouvez alors envoyer vers n'importe quelle adresse.
  - SOIT, à défaut, l'adresse de test onboarding@resend.dev comme
    expéditeur : dans ce cas, Resend n'autorise l'envoi QUE vers l'adresse
    e-mail du titulaire du compte Resend lui-même (--destinataire doit
    alors être cette adresse, sinon Resend refusera silencieusement ou
    renverra une erreur explicite - le script affiche la réponse complète
    dans les deux cas).

Usage :
    export RESEND_API_KEY="re_votre_vraie_cle"
    export EMAIL_FROM="Plateforme Workflows <onboarding@resend.dev>"   # ou votre domaine vérifié
    python3 scripts/tester_resend_reel.py --destinataire vous@exemple.com

Variante avec toutes les autres variables d'environnement déjà en place
(fichier .env du projet) :
    python3 scripts/tester_resend_reel.py --destinataire vous@exemple.com --env-file .env
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path


def _charger_env_file(chemin: str) -> None:
    fichier = Path(chemin)
    if not fichier.exists():
        print(f"[Avertissement] Fichier d'environnement introuvable : {chemin}", file=sys.stderr)
        return
    for ligne in fichier.read_text().splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


def _lire_arguments() -> argparse.Namespace:
    parseur = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parseur.add_argument("--destinataire", required=True, help="Adresse e-mail réelle qui doit recevoir le test")
    parseur.add_argument("--env-file", default=None, help="Chemin d'un fichier .env à charger avant l'envoi")
    return parseur.parse_args()


async def main() -> None:
    args = _lire_arguments()
    if args.env_file:
        _charger_env_file(args.env_file)

    for variable in ("RESEND_API_KEY", "EMAIL_FROM"):
        if not os.environ.get(variable):
            print(f"[Erreur] La variable d'environnement {variable} n'est pas définie.", file=sys.stderr)
            print("Voir l'en-tête de ce script pour l'usage attendu.", file=sys.stderr)
            sys.exit(1)

    # Valeurs par defaut minimales pour importer app.* sans planter sur des
    # settings non lies a l'envoi d'e-mail (non utilisees par ce test).
    os.environ.setdefault("SECRET_KEY", "test-reel-resend")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("JWT_SECRET_KEY", "test-reel-resend")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.core.config import get_settings
    from app.services import email_service

    settings = get_settings()

    print(f"Expéditeur configuré (EMAIL_FROM) : {settings.email_from}")
    print(f"Destinataire du test               : {args.destinataire}")
    if "onboarding@resend.dev" in settings.email_from:
        print(
            "[Attention] Vous utilisez l'adresse de test onboarding@resend.dev : "
            "Resend n'autorisera l'envoi que vers l'adresse e-mail du titulaire du compte "
            "(section 14.2.1 du CDC). Si --destinataire est différent, l'envoi échouera."
        )
    print("\nEnvoi en cours via le vrai SDK Resend (app.services.email_service.envoyer_email)...\n")

    try:
        await email_service.envoyer_email(
            destinataire=args.destinataire,
            sujet="Test réel d'intégration Resend — Plateforme Workflows",
            corps_html=(
                "<p>Ceci est un test réel d'envoi via l'intégration Resend de la "
                "Plateforme d'Approbation de Workflows (section 14.2 du CDC technique).</p>"
                "<p>Si vous recevez cet e-mail, l'intégration fonctionne correctement "
                "en conditions réelles, au-delà des mocks utilisés dans la suite de tests automatisée.</p>"
            ),
        )
    except Exception as exc:
        print(f"❌ ÉCHEC DE L'ENVOI : {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "\nCauses fréquentes : clé API invalide/révoquée, domaine d'expéditeur non "
            "vérifié dans Resend, ou --destinataire différent du titulaire du compte si "
            "vous utilisez onboarding@resend.dev.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("✅ Appel à l'API Resend terminé sans exception.")
    print("Vérifiez la boîte de réception (et les spams) de", args.destinataire)
    print(
        "Vous pouvez aussi consulter le tableau de bord Resend "
        "(https://resend.com/emails) pour confirmer le statut réel de livraison "
        "(sent / delivered / bounced) - cet appel confirme seulement que Resend a "
        "accepté la requête, pas que le message est arrivé."
    )


if __name__ == "__main__":
    asyncio.run(main())
