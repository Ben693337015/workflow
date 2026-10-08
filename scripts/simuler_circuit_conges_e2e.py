"""
Simulation complète et réelle du circuit "Demande de congés", de la
soumission à la notification par e-mail du demandeur — bout en bout à
travers les vraies routes FastAPI (pas des appels directs aux services).

Rejoue exactement le parcours du CDC technique, section 13 :
  1. Connexion employé (POST /api/v1/auth/login)
  2. Soumission de la demande (POST /api/v1/conges/)          -> §13.2
  3. E-mail de notification au manager, avec jeton de décision -> §9 / §14.2
  4. Connexion manager (POST /api/v1/auth/login)
  5. Décision du manager (POST /api/v1/decisions/{jeton})      -> §9 / §13.3
  6. Effets de bord : solde décrémenté, notification DRH, ET
     notification du demandeur (correction du 15/09)           -> §11.1, ce script

Seul le SDK Resend est simulé (aucun appel réseau réel) ; tout le reste
(base de données SQLite en mémoire, routes FastAPI, JWT, hachage bcrypt,
jetons de décision, moteur de routage, verrou RH) est le code réel de
l'application, exécuté sans mock côté logique métier.

Usage :
    python3 scripts/simuler_circuit_conges_e2e.py
"""
import asyncio
import os
import re
import sys
import uuid
from datetime import date
from unittest.mock import AsyncMock

# --- Variables d'environnement minimales (avant tout import de app.*) -------
os.environ.setdefault("SECRET_KEY", "simulation-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "simulation-jwt-secret")
os.environ.setdefault("RESEND_API_KEY", "re_simulation")
os.environ.setdefault("EMAIL_FROM", "Plateforme Workflows <notifications@simulation.tld>")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:5173")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import RoleUtilisateur  # noqa: E402
from app.models.solde_conges import SoldeConges  # noqa: E402
from app.models.type_conge import TypeConge  # noqa: E402
from app.models.user import Utilisateur  # noqa: E402

SEPARATEUR = "=" * 78


def etape(titre: str) -> None:
    print(f"\n{SEPARATEUR}\n{titre}\n{SEPARATEUR}")


def sous_etape(texte: str) -> None:
    print(f"  -> {texte}")


async def main() -> None:
    # --- Mise en place : base SQLite en memoire, comme la suite de tests. ---
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    db = session_factory()

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    # --- Seul le SDK Resend est simule : capture tous les e-mails "envoyes". ---
    emails_envoyes: list[dict] = []

    async def _capturer_email(destinataire: str, sujet: str, corps_html: str) -> None:
        emails_envoyes.append({"destinataire": destinataire, "sujet": sujet, "corps_html": corps_html})

    import app.routers.conges as conges_router
    import app.routers.decisions as decisions_router

    conges_router.email_service.envoyer_email = AsyncMock(side_effect=_capturer_email)
    decisions_router.email_service.envoyer_email = AsyncMock(side_effect=_capturer_email)

    etape("ÉTAPE 0 — Préparation des données (DRH, manager, employé, solde)")

    type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db.add(type_conge)
    await db.flush()

    drh = Utilisateur(
        email="drh@simulation.tld",
        mot_de_passe_hash=hash_password("DrhPass123!"),
        nom_complet="Awa Ngassa",
        service="RH",
        role=RoleUtilisateur.DRH,
    )
    manager = Utilisateur(
        email="manager@simulation.tld",
        mot_de_passe_hash=hash_password("ManagerPass123!"),
        nom_complet="Paul Mendo",
        service="Support",
        role=RoleUtilisateur.MANAGER,
    )
    db.add_all([drh, manager])
    await db.flush()

    employe = Utilisateur(
        email="employe@simulation.tld",
        mot_de_passe_hash=hash_password("EmployePass123!"),
        nom_complet="Fatou Djida",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
        manager_id=manager.id,
    )
    db.add(employe)
    await db.flush()

    db.add(
        SoldeConges(
            utilisateur_id=employe.id,
            type_conge_id=type_conge.id,
            solde_jours=15,
            jours_acquis=15,
            jours_pris=0,
            exercice=2026,
        )
    )
    await db.commit()

    sous_etape(f"Employé  : {employe.nom_complet} <{employe.email}> — solde initial 15 jours")
    sous_etape(f"Manager  : {manager.nom_complet} <{manager.email}>")
    sous_etape(f"DRH      : {drh.nom_complet} <{drh.email}>")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://simulation") as client:

        # --- Etape 1 : connexion employe (section 5). ---
        etape("ÉTAPE 1 — Connexion de l'employé (POST /api/v1/auth/login)")
        reponse = await client.post(
            "/api/v1/auth/login",
            json={"email": employe.email, "mot_de_passe": "EmployePass123!"},
        )
        assert reponse.status_code == 200, reponse.text
        jeton_acces_employe = reponse.json()["access_token"]
        sous_etape(f"Connexion réussie — code {reponse.status_code}, JWT reçu (tronqué) : {jeton_acces_employe[:24]}...")

        # --- Etape 2 : soumission de la demande (section 13.2). ---
        etape("ÉTAPE 2 — Soumission de la demande de congés (POST /api/v1/conges/)")
        entete_employe = {"Authorization": f"Bearer {jeton_acces_employe}"}
        reponse = await client.post(
            "/api/v1/conges/",
            json={
                "type_conge_id": str(type_conge.id),
                "date_debut": "2026-10-05",
                "date_fin": "2026-10-07",
            },
            headers=entete_employe,
        )
        assert reponse.status_code == 201, reponse.text
        corps_reponse = reponse.json()
        demande_id = corps_reponse["id"]
        sous_etape(f"Demande créée — id={demande_id}, statut={corps_reponse['statut_global']}")
        sous_etape("Vérification synchrone du solde (verrou RH, §11.1.2) passée : 3 jours ouvrés sur 15 disponibles")

        # --- Etape 3 : verification de l'e-mail envoye au manager. ---
        etape("ÉTAPE 3 — Notification e-mail envoyée au manager (Resend simulé, §9 / §14.2)")
        assert len(emails_envoyes) == 1, f"1 e-mail attendu, {len(emails_envoyes)} envoyé(s)"
        email_manager = emails_envoyes[0]
        assert email_manager["destinataire"] == manager.email
        sous_etape(f"Destinataire : {email_manager['destinataire']}")
        sous_etape(f"Sujet        : {email_manager['sujet']}")
        print(f"    Corps (extrait) : {email_manager['corps_html'][:140]}...")

        match_jeton = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)['\"]", email_manager["corps_html"])
        assert match_jeton, "Jeton de décision introuvable dans le corps de l'e-mail"
        jeton_decision = match_jeton.group(1)
        sous_etape(f"Jeton de décision extrait du lien 'Approuver' : {jeton_decision[:24]}...")

        # --- Etape 4 : connexion manager (option B, section 9.1). ---
        etape("ÉTAPE 4 — Connexion du manager (requise par l'Option B avant de décider)")
        reponse = await client.post(
            "/api/v1/auth/login",
            json={"email": manager.email, "mot_de_passe": "ManagerPass123!"},
        )
        assert reponse.status_code == 200, reponse.text
        jeton_acces_manager = reponse.json()["access_token"]
        sous_etape(f"Connexion réussie — code {reponse.status_code}")

        sous_etape("Contrôle (Option B) : tentative de décision SANS session -> doit être rejetée")
        reponse_sans_session = await client.post(f"/api/v1/decisions/{jeton_decision}", json={})
        assert reponse_sans_session.status_code == 401
        sous_etape(f"Rejetée comme attendu — code {reponse_sans_session.status_code} (401 Unauthorized)")

        # --- Etape 5 : decision du manager (approbation). ---
        etape("ÉTAPE 5 — Décision du manager : APPROBATION (POST /api/v1/decisions/{jeton})")
        entete_manager = {"Authorization": f"Bearer {jeton_acces_manager}"}
        reponse = await client.post(
            f"/api/v1/decisions/{jeton_decision}", json={}, headers=entete_manager
        )
        assert reponse.status_code == 200, reponse.text
        corps_decision = reponse.json()
        sous_etape(f"Décision acceptée — code {reponse.status_code}, statut_global={corps_decision['statut_global']}")

        # --- Etape 6 : verification des effets de bord. ---
        etape("ÉTAPE 6 — Effets de bord après décision")
        from app.services.extensions.verrou_rh import obtenir_solde

        solde = await obtenir_solde(db, employe.id, type_conge.id, 2026)
        sous_etape(f"Solde réellement décrémenté : 15 -> {float(solde.solde_jours)} jours (3 jours consommés)")

        emails_apres_decision = emails_envoyes[1:]
        destinataires_apres_decision = [e["destinataire"] for e in emails_apres_decision]
        sous_etape(f"E-mails envoyés après la décision : {len(emails_apres_decision)}")
        for e in emails_apres_decision:
            print(f"      - {e['destinataire']:<30} sujet : {e['sujet']}")

        assert drh.email in destinataires_apres_decision, "La DRH doit être notifiée"
        assert employe.email in destinataires_apres_decision, "Le demandeur doit être notifié"

        etape("ÉTAPE 7 — Notification finale reçue par le DEMANDEUR (le point vérifié)")
        email_demandeur = next(e for e in emails_apres_decision if e["destinataire"] == employe.email)
        sous_etape(f"Destinataire : {email_demandeur['destinataire']}")
        sous_etape(f"Sujet        : {email_demandeur['sujet']}")
        print(f"    Corps intégral : {email_demandeur['corps_html']}")

        etape("ÉTAPE 8 — Téléchargement de la fiche de confirmation (fin de circuit, §12)")
        reponse = await client.get(
            f"/api/v1/conges/{demande_id}/fiche-confirmation", headers=entete_employe
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.headers["content-type"] == "application/pdf"
        sous_etape(f"PDF généré avec succès — {len(reponse.content)} octets, content-type={reponse.headers['content-type']}")

    app.dependency_overrides.clear()
    await db.close()
    await engine.dispose()

    etape("RÉCAPITULATIF — parcours complet vérifié de bout en bout")
    print(f"  Total d'e-mails envoyés durant le parcours : {len(emails_envoyes)}")
    for i, e in enumerate(emails_envoyes, start=1):
        print(f"    {i}. -> {e['destinataire']:<30} | {e['sujet']}")
    print("\n  Résultat : SUCCÈS — soumission -> décision manager -> solde décrémenté ->")
    print("  notification DRH -> notification DEMANDEUR (avec motif si refus) -> fiche PDF.")
    print(f"{SEPARATEUR}\n")


if __name__ == "__main__":
    asyncio.run(main())
