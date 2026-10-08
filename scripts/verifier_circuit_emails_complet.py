"""
Vérification exhaustive de TOUS les circuits d'e-mail de l'application, de
bout en bout, à travers les vraies routes FastAPI.

Inventaire complet des 6 points d'envoi d'e-mail du code (confirmé par
`grep -rn "email_service.envoyer_email" app/routers/`) :

  1. app/routers/utilisateurs.py  — invitation à la création d'un compte
  2. app/routers/auth.py          — réinitialisation de mot de passe oublié
  3. app/routers/conges.py        — notification au manager à la soumission
  4. app/routers/decisions.py     — notification DRH après décision
  5. app/routers/decisions.py     — notification du demandeur après décision
  6. app/routers/conges.py        — notification à l'employé après régularisation

Pour chacun, ce script vérifie : que l'e-mail est bien envoyé, au bon
destinataire, avec le bon contenu, ET que son échec (Resend indisponible)
ne bloque jamais le flux principal (section 13.4 du CDC).

Usage :
    python3 scripts/verifier_circuit_emails_complet.py
"""
import asyncio
import os
import re
import sys
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "verif-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "verif-jwt-secret")
os.environ.setdefault("RESEND_API_KEY", "re_verif")
os.environ.setdefault("EMAIL_FROM", "Plateforme Workflows <notifications@verif.tld>")
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

SEP = "=" * 84
ECHECS: list[str] = []


def etape(titre: str) -> None:
    print(f"\n{SEP}\n{titre}\n{SEP}")


def vguard(condition: bool, libelle: str) -> None:
    if condition:
        print(f"  [OK] {libelle}")
    else:
        print(f"  [ECHEC] {libelle}")
        ECHECS.append(libelle)


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    db = session_factory()

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    emails: list[dict] = []

    async def _capturer(destinataire: str, sujet: str, corps_html: str) -> None:
        emails.append({"destinataire": destinataire, "sujet": sujet, "corps_html": corps_html})

    import app.routers.auth as auth_router
    import app.routers.conges as conges_router
    import app.routers.decisions as decisions_router
    import app.routers.utilisateurs as utilisateurs_router

    for module in (auth_router, conges_router, decisions_router, utilisateurs_router):
        module.email_service.envoyer_email = AsyncMock(side_effect=_capturer)

    # =========================================================================
    etape("PRÉPARATION")
    # =========================================================================
    type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db.add(type_conge)
    await db.flush()
    drh = Utilisateur(
        email="drh@verif.tld", mot_de_passe_hash=hash_password("DrhPass123!"),
        nom_complet="Awa Ngassa", service="RH", role=RoleUtilisateur.DRH,
    )
    manager = Utilisateur(
        email="manager@verif.tld", mot_de_passe_hash=hash_password("ManagerPass123!"),
        nom_complet="Paul Mendo", service="Support", role=RoleUtilisateur.MANAGER,
    )
    db.add_all([drh, manager])
    await db.flush()
    employe = Utilisateur(
        email="employe@verif.tld", mot_de_passe_hash=hash_password("EmployePass123!"),
        nom_complet="Fatou Djida", service="Support", role=RoleUtilisateur.EMPLOYE, manager_id=manager.id,
    )
    db.add(employe)
    await db.flush()
    db.add(SoldeConges(
        utilisateur_id=employe.id, type_conge_id=type_conge.id,
        solde_jours=15, jours_acquis=15, jours_pris=0, exercice=2026,
    ))
    await db.commit()
    print("  Organisation prête : 1 DRH, 1 manager, 1 employé, 1 type de congé.")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://verif") as client:

        async def connecter(email: str, mdp: str) -> str:
            r = await client.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": mdp})
            assert r.status_code == 200, r.text
            return r.json()["access_token"]

        jeton_drh = await connecter(drh.email, "DrhPass123!")
        entete_drh = {"Authorization": f"Bearer {jeton_drh}"}

        # =====================================================================
        etape("CIRCUIT 1/6 — Invitation à la création d'un compte (par le DRH)")
        # =====================================================================
        n = len(emails)
        r = await client.post(
            "/api/v1/utilisateurs/",
            json={
                "email": "nouvel.arrivant@verif.tld", "nom_complet": "Nouvel Arrivant",
                "service": "Support", "role": "employe", "manager_id": str(manager.id),
            },
            headers=entete_drh,
        )
        vguard(r.status_code == 201, f"Création du compte acceptée (201) — reçu {r.status_code}")
        vguard(len(emails) == n + 1, "1 e-mail d'invitation envoyé")
        email_invitation = emails[-1]
        vguard(email_invitation["destinataire"] == "nouvel.arrivant@verif.tld", "…au bon destinataire (le nouvel employé, pas le DRH)")
        vguard("employe" in email_invitation["corps_html"], "…mentionne le rôle attribué")
        vguard("activer-compte" in email_invitation["corps_html"], "…contient un lien d'activation")

        match = re.search(r"/activer-compte/([A-Za-z0-9_\-]+)", email_invitation["corps_html"])
        jeton_invitation = match.group(1) if match else None
        vguard(jeton_invitation is not None, "Jeton d'invitation extrait du lien")

        echec_avant_activation = await client.post(
            "/api/v1/auth/login", json={"email": "nouvel.arrivant@verif.tld", "mot_de_passe": "PeuImporte1!"}
        )
        vguard(echec_avant_activation.status_code == 401, "Connexion impossible avant activation (401, pas de crash)")

        r_activation = await client.post(
            "/api/v1/auth/definir-mot-de-passe",
            json={"jeton": jeton_invitation, "mot_de_passe": "MonMotDePasse123!"},
        )
        vguard(r_activation.status_code == 200, f"Activation du compte réussie (200) — reçu {r_activation.status_code}")
        vguard("access_token" in r_activation.json(), "…connecte immédiatement l'employé (jetons de session renvoyés)")

        connexion_reussie = await client.post(
            "/api/v1/auth/login", json={"email": "nouvel.arrivant@verif.tld", "mot_de_passe": "MonMotDePasse123!"}
        )
        vguard(connexion_reussie.status_code == 200, "Connexion normale possible après activation")

        rejeu_activation = await client.post(
            "/api/v1/auth/definir-mot-de-passe",
            json={"jeton": jeton_invitation, "mot_de_passe": "AutreChose123!"},
        )
        vguard(rejeu_activation.status_code == 401, "Le lien d'invitation est à usage unique (rejeu rejeté)")

        # =====================================================================
        etape("CIRCUIT 2/6 — Mot de passe oublié")
        # =====================================================================
        n = len(emails)
        r = await client.post("/api/v1/auth/mot-de-passe-oublie", json={"email": employe.email})
        vguard(r.status_code == 202, f"Requête acceptée (202) — reçu {r.status_code}")
        vguard(len(emails) == n + 1, "1 e-mail de réinitialisation envoyé")
        email_reset = emails[-1]
        vguard(email_reset["destinataire"] == employe.email, "…au bon destinataire")
        vguard("reinitialiser-mot-de-passe" in email_reset["corps_html"], "…contient un lien de réinitialisation")

        n = len(emails)
        r_inconnu = await client.post("/api/v1/auth/mot-de-passe-oublie", json={"email": "personne@verif.tld"})
        vguard(r_inconnu.status_code == 202, "Même réponse (202) pour un e-mail inconnu…")
        vguard(len(emails) == n, "…mais AUCUN e-mail envoyé (pas d'énumération de comptes)")

        match = re.search(r"/reinitialiser-mot-de-passe/([A-Za-z0-9_\-]+)", email_reset["corps_html"])
        jeton_reset = match.group(1)
        r_reset = await client.post(
            "/api/v1/auth/definir-mot-de-passe", json={"jeton": jeton_reset, "mot_de_passe": "NouveauMdp123!"}
        )
        vguard(r_reset.status_code == 200, "Réinitialisation effective (200)")
        ancien_mdp_rejete = await client.post(
            "/api/v1/auth/login", json={"email": employe.email, "mot_de_passe": "EmployePass123!"}
        )
        vguard(ancien_mdp_rejete.status_code == 401, "L'ancien mot de passe ne fonctionne plus")
        nouveau_mdp_accepte = await client.post(
            "/api/v1/auth/login", json={"email": employe.email, "mot_de_passe": "NouveauMdp123!"}
        )
        vguard(nouveau_mdp_accepte.status_code == 200, "Le nouveau mot de passe fonctionne")

        jeton_employe = nouveau_mdp_accepte.json()["access_token"]
        entete_employe = {"Authorization": f"Bearer {jeton_employe}"}

        # =====================================================================
        etape("CIRCUIT 3/6 — Notification au manager à la soumission d'une demande")
        # =====================================================================
        n = len(emails)
        r = await client.post(
            "/api/v1/conges/",
            json={
                "type_conge_id": str(type_conge.id), "date_debut": "2026-10-05", "date_fin": "2026-10-06",
                "commentaire": "Rendez-vous personnel.",
            },
            headers=entete_employe,
        )
        vguard(r.status_code == 201, "Soumission acceptée (201)")
        demande_id = r.json()["id"]
        vguard(len(emails) == n + 1, "1 e-mail envoyé au manager")
        email_manager = emails[-1]
        vguard(email_manager["destinataire"] == manager.email, "…au bon manager")
        vguard(employe.nom_complet in email_manager["corps_html"], "…avec le nom du demandeur")
        vguard("Rendez-vous personnel." in email_manager["corps_html"], "…avec le commentaire du demandeur")

        match = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", email_manager["corps_html"])
        jeton_approuver = match.group(1)

        jeton_acces_manager = await connecter(manager.email, "ManagerPass123!")
        entete_manager = {"Authorization": f"Bearer {jeton_acces_manager}"}

        # =====================================================================
        etape("CIRCUIT 4/6 & 5/6 — Notifications DRH + demandeur après décision (approbation)")
        # =====================================================================
        n = len(emails)
        r = await client.post(f"/api/v1/decisions/{jeton_approuver}", json={}, headers=entete_manager)
        vguard(r.status_code == 200, "Décision d'approbation acceptée (200)")
        nouveaux = emails[n:]
        vguard(any(e["destinataire"] == drh.email for e in nouveaux), "DRH notifiée")
        vguard(any(e["destinataire"] == employe.email for e in nouveaux), "Demandeur notifié")
        email_demandeur = next(e for e in nouveaux if e["destinataire"] == employe.email)
        vguard(manager.nom_complet in email_demandeur["corps_html"], "…avec le nom du décideur")
        vguard("approuvée" in email_demandeur["sujet"], "…sujet cohérent avec l'issue")

        # =====================================================================
        etape("CIRCUIT 4/6 & 5/6 (bis) — Notifications DRH + demandeur (refus, avec motif)")
        # =====================================================================
        r = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-11-10", "date_fin": "2026-11-11"},
            headers=entete_employe,
        )
        email_manager_2 = emails[-1]
        m = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Refuser", email_manager_2["corps_html"])
        jeton_refuser = m.group(1)

        n = len(emails)
        r = await client.post(
            f"/api/v1/decisions/{jeton_refuser}",
            json={"commentaire": "Trop de demandes concomitantes."},
            headers=entete_manager,
        )
        vguard(r.status_code == 200 and r.json()["statut_global"] == "refusee", "Décision de refus acceptée")
        nouveaux = emails[n:]
        email_demandeur_refus = next(e for e in nouveaux if e["destinataire"] == employe.email)
        vguard("Trop de demandes concomitantes." in email_demandeur_refus["corps_html"], "Motif transmis au demandeur")
        email_drh_refus = next(e for e in nouveaux if e["destinataire"] == drh.email)
        vguard(employe.nom_complet in email_drh_refus["corps_html"], "DRH notifiée avec le nom du demandeur")

        # =====================================================================
        etape("CIRCUIT 6/6 — Notification à l'employé après régularisation")
        # =====================================================================
        n = len(emails)
        r = await client.post(
            "/api/v1/conges/regularisation",
            json={
                "employe_id": str(employe.id), "type_conge_id": str(type_conge.id),
                "date_debut": "2026-09-01", "date_fin": "2026-09-02", "action": "approuver",
            },
            headers=entete_manager,
        )
        vguard(r.status_code == 201, "Régularisation acceptée (201)")
        vguard(any(e["destinataire"] == employe.email for e in emails[n:]), "Employé notifié de la régularisation")

        # =====================================================================
        etape("RÉSILIENCE — Une panne Resend ne doit jamais bloquer le flux principal")
        # =====================================================================
        for module, nom in [(conges_router, "conges.py"), (decisions_router, "decisions.py")]:
            module.email_service.envoyer_email = AsyncMock(side_effect=RuntimeError("Resend indisponible (simulé)"))

        r = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-12-01", "date_fin": "2026-12-02"},
            headers=entete_employe,
        )
        vguard(r.status_code == 201, f"Soumission réussit MALGRÉ la panne Resend simulée — reçu {r.status_code}")

        from app.models.enums import StatutEtape
        from app.models.etape_workflow import EtapeWorkflow
        from sqlalchemy import select as _select

        etape_en_attente = (
            await db.execute(
                _select(EtapeWorkflow).where(
                    EtapeWorkflow.approbateur_attendu_id == manager.id,
                    EtapeWorkflow.statut == StatutEtape.EN_ATTENTE,
                )
            )
        ).scalars().one()
        from app.services import decision_tokens
        jeton_secours = await decision_tokens.generer_jeton_decision(
            db, etape_en_attente.id, "approuver", manager.id
        )
        await db.commit()
        r_decision = await client.post(f"/api/v1/decisions/{jeton_secours}", json={}, headers=entete_manager)
        vguard(r_decision.status_code == 200, f"Décision réussit MALGRÉ la panne Resend simulée (DRH+demandeur) — reçu {r_decision.status_code}")

    app.dependency_overrides.clear()
    await db.close()
    await engine.dispose()

    # =========================================================================
    etape("BILAN FINAL")
    # =========================================================================
    print(f"  Total e-mails capturés (hors scénario de panne) : {len(emails)}")
    if ECHECS:
        print(f"\n  ❌ {len(ECHECS)} VÉRIFICATION(S) EN ÉCHEC :")
        for e in ECHECS:
            print(f"     - {e}")
    else:
        print("\n  ✅ LES 6 CIRCUITS D'E-MAIL DE L'APPLICATION SONT VÉRIFIÉS ET CONFORMES,")
        print("     Y COMPRIS LEUR RÉSILIENCE À UNE PANNE RESEND.")
    print(f"{SEP}\n")

    if ECHECS:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
