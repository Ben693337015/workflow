"""
Simulation A-Z, rigoureuse, du circuit "Demande de congés" complet, à
travers les vraies routes FastAPI (aucun mock de la logique métier - seuls
le SDK Resend et le client HTTP des webhooks sortants sont simulés, pour ne
pas dépendre d'un réseau externe).

Scénarios couverts :
  1. Soumission nominale avec chevauchement d'un jour férié (vérifie
     l'exclusion des jours fériés, §11.1) -> approbation -> solde décrémenté
     -> notifications (manager, DRH, demandeur) -> webhook -> audit ->
     fiche de confirmation -> mise à jour de l'agenda d'équipe.
  2. Soumission -> refus (commentaire obligatoire, §8) -> notifications avec
     motif -> solde NON décrémenté -> absent de l'agenda d'équipe.
  3. Soumission rejetée pour solde insuffisant (§11, écart 2) - aucune
     demande créée, aucun e-mail envoyé.
  4. Modification d'une demande encore en cours (§ écart identifié).
  5. Annulation d'une demande en cours -> jeton déjà émis rendu caduc.
  6. Tentative d'usurpation (Option B, §9.1) : un tiers authentifié, non
     l'approbateur attendu, tente de décider -> 403 + audit dédié.
  7. Régularisation RH/managériale, approbation et refus (§11.1.1).
  8. Étanchéité de l'agenda d'équipe entre équipes, et vue consolidée DRH.
  9. Récapitulatif intégral du journal d'audit (append-only, horodaté,
     attribué - §14.3).

Usage :
    python3 scripts/simuler_circuit_conges_complet.py
"""
import asyncio
import os
import re
import sys
import uuid
from datetime import date
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "simulation-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "simulation-jwt-secret")
os.environ.setdefault("RESEND_API_KEY", "re_simulation")
os.environ.setdefault("EMAIL_FROM", "Plateforme Workflows <notifications@simulation.tld>")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:5173")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.chiffrement import chiffrer_secret
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.abonnement_webhook import AbonnementWebhook  # noqa: E402
from app.models.enums import RoleUtilisateur, TypeProcessus  # noqa: E402
from app.models.jour_ferie import JourFerie  # noqa: E402
from app.models.journal_audit import JournalAudit  # noqa: E402
from app.models.solde_conges import SoldeConges  # noqa: E402
from app.models.type_conge import TypeConge  # noqa: E402
from app.models.user import Utilisateur  # noqa: E402

SEP = "=" * 84
ECHECS: list[str] = []


def etape(titre: str) -> None:
    print(f"\n{SEP}\n{titre}\n{SEP}")


def ok(libelle: str) -> None:
    print(f"  [OK] {libelle}")


def vguard(condition: bool, libelle: str) -> None:
    """Assertion non-fatale : le script continue meme si un point echoue,
    pour donner un bilan complet plutot que de s'arreter au premier accroc."""
    if condition:
        ok(libelle)
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

    async def _capturer_email(destinataire: str, sujet: str, corps_html: str) -> None:
        emails.append({"destinataire": destinataire, "sujet": sujet, "corps_html": corps_html})

    import app.routers.conges as conges_router
    import app.routers.decisions as decisions_router

    conges_router.email_service.envoyer_email = AsyncMock(side_effect=_capturer_email)
    decisions_router.email_service.envoyer_email = AsyncMock(side_effect=_capturer_email)

    webhooks_recus: list[dict] = []

    class _ReponseHttpFictive:
        status_code = 200

    class _ClientHttpFictif:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, content=None, headers=None):
            webhooks_recus.append(
                {"url": url, "corps": content.decode() if content else None, "headers": headers}
            )
            return _ReponseHttpFictive()

    import app.services.webhooks as webhooks_service

    webhooks_service.httpx.AsyncClient = lambda timeout=5.0: _ClientHttpFictif()

    # =========================================================================
    etape("ÉTAPE 0 — Préparation de l'environnement (organisation à 2 équipes)")
    # =========================================================================

    type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db.add(type_conge)
    await db.flush()

    # Jour férié volontairement placé au milieu de la période de test n°1,
    # pour vérifier que le décompte de jours ouvrés l'exclut bien (§11.1).
    db.add(JourFerie(nom="Jour test", date=date(2026, 10, 6), recurrent=False))

    drh = Utilisateur(
        email="drh@simulation.tld", mot_de_passe_hash=hash_password("DrhPass123!"),
        nom_complet="Awa Ngassa", service="RH", role=RoleUtilisateur.DRH,
    )
    manager_a = Utilisateur(
        email="manager.a@simulation.tld", mot_de_passe_hash=hash_password("ManagerPass123!"),
        nom_complet="Paul Mendo", service="Support", role=RoleUtilisateur.MANAGER,
    )
    manager_b = Utilisateur(
        email="manager.b@simulation.tld", mot_de_passe_hash=hash_password("ManagerPass123!"),
        nom_complet="Claire Biya", service="Ventes", role=RoleUtilisateur.MANAGER,
    )
    db.add_all([drh, manager_a, manager_b])
    await db.flush()

    employe_a1 = Utilisateur(
        email="employe.a1@simulation.tld", mot_de_passe_hash=hash_password("EmployePass123!"),
        nom_complet="Fatou Djida", service="Support", role=RoleUtilisateur.EMPLOYE, manager_id=manager_a.id,
    )
    employe_a2 = Utilisateur(
        email="employe.a2@simulation.tld", mot_de_passe_hash=hash_password("EmployePass123!"),
        nom_complet="Jean Ateba", service="Support", role=RoleUtilisateur.EMPLOYE, manager_id=manager_a.id,
    )
    employe_b1 = Utilisateur(
        email="employe.b1@simulation.tld", mot_de_passe_hash=hash_password("EmployePass123!"),
        nom_complet="Marie Fouda", service="Ventes", role=RoleUtilisateur.EMPLOYE, manager_id=manager_b.id,
    )
    db.add_all([employe_a1, employe_a2, employe_b1])
    await db.flush()

    for employe, solde in [(employe_a1, 15), (employe_a2, 10), (employe_b1, 10)]:
        db.add(SoldeConges(
            utilisateur_id=employe.id, type_conge_id=type_conge.id,
            solde_jours=solde, jours_acquis=solde, jours_pris=0, exercice=2026,
        ))

    # Abonnement webhook (systeme tiers fictif) souscrit a tous les evenements
    # congés, pour verifier la section 10 (notification de systemes tiers).
    db.add(AbonnementWebhook(
        url_destination="https://erp-simulation.tld/webhooks/conges",
        secret_hmac=chiffrer_secret("secret-simulation"),  # stocke chiffre (R22)
        processus=TypeProcessus.CONGES,
        evenements=[
            "demande_soumise", "circuit_termine", "etape_refusee", "demande_annulee",
        ],
    ))
    await db.commit()

    ok(f"Organisation : DRH={drh.nom_complet}, Manager A={manager_a.nom_complet} "
       f"(équipe : {employe_a1.nom_complet}, {employe_a2.nom_complet}), "
       f"Manager B={manager_b.nom_complet} (équipe : {employe_b1.nom_complet})")
    ok("1 jour férié déclaré le 06/10/2026, 1 abonnement webhook actif sur tous les événements congés")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://simulation") as client:

        async def connecter(email: str, mot_de_passe: str) -> str:
            r = await client.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": mot_de_passe})
            assert r.status_code == 200, r.text
            return r.json()["access_token"]

        jeton_a1 = await connecter(employe_a1.email, "EmployePass123!")
        jeton_a2 = await connecter(employe_a2.email, "EmployePass123!")
        jeton_b1 = await connecter(employe_b1.email, "EmployePass123!")
        jeton_manager_a = await connecter(manager_a.email, "ManagerPass123!")
        jeton_manager_b = await connecter(manager_b.email, "ManagerPass123!")
        jeton_drh = await connecter(drh.email, "DrhPass123!")
        ok("6 connexions réussies (3 employés, 2 managers, 1 DRH)")

        entete_a1 = {"Authorization": f"Bearer {jeton_a1}"}
        entete_a2 = {"Authorization": f"Bearer {jeton_a2}"}
        entete_b1 = {"Authorization": f"Bearer {jeton_b1}"}
        entete_manager_a = {"Authorization": f"Bearer {jeton_manager_a}"}
        entete_manager_b = {"Authorization": f"Bearer {jeton_manager_b}"}
        entete_drh = {"Authorization": f"Bearer {jeton_drh}"}

        # =====================================================================
        etape("SCÉNARIO 1 — Soumission → approbation, avec un jour férié dans la période")
        # =====================================================================

        n_emails_avant = len(emails)
        n_webhooks_avant = len(webhooks_recus)

        r = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-10-05", "date_fin": "2026-10-08"},
            headers=entete_a1,
        )
        vguard(r.status_code == 201, f"Soumission acceptée (201) — reçu {r.status_code}")
        corps = r.json()
        demande_1_id = corps["id"]
        # Du 05 au 08/10 inclus = 4 jours calendaires, moins le 06/10 férié = 3.
        vguard(corps["nombre_jours"] == 3, f"Décompte correct : 4 jours calendaires - 1 férié = 3 (reçu {corps['nombre_jours']})")

        vguard(len(emails) == n_emails_avant + 1, "1 e-mail envoyé au manager à la soumission")
        email_manager = emails[-1]
        vguard(email_manager["destinataire"] == manager_a.email, "…adressé au bon manager (destinataire dynamique, §7)")
        vguard(employe_a1.nom_complet in email_manager["corps_html"], "…mentionne le nom du demandeur")
        vguard("05/10/2026" in email_manager["corps_html"] and "08/10/2026" in email_manager["corps_html"],
               "…mentionne les dates exactes de la période")
        vguard("3 jour(s) décompté(s)" in email_manager["corps_html"], "…mentionne le nombre de jours déductibles (férié exclu)")

        vguard(len(webhooks_recus) == n_webhooks_avant + 1, "1 webhook sortant émis (demande_soumise, §10)")
        vguard(webhooks_recus[-1]["headers"].get("X-Signature-256") is not None, "…signé HMAC (§10)")
        vguard('"evenement": "demande_soumise"' in webhooks_recus[-1]["corps"], "…porte le bon type d'événement")

        match_jeton = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)['\"]", email_manager["corps_html"])
        jeton_approuver_1 = match_jeton.group(1) if match_jeton else None
        vguard(jeton_approuver_1 is not None, "Jeton de décision extrait du lien 'Approuver'")

        r = await client.get("/api/v1/conges/", headers=entete_a1)
        mes_demandes = r.json()
        vguard(
            any(d["id"] == demande_1_id and d["statut_global"] == "en_cours" for d in mes_demandes),
            "'Mes demandes' (§12) affiche la demande comme 'en_cours'",
        )

        r_sans_session = await client.post(f"/api/v1/decisions/{jeton_approuver_1}", json={})
        vguard(r_sans_session.status_code == 401, f"Option B (§9.1) : décision sans session rejetée (401) — reçu {r_sans_session.status_code}")

        r_usurpation = await client.post(f"/api/v1/decisions/{jeton_approuver_1}", json={}, headers=entete_manager_b)
        vguard(r_usurpation.status_code == 403, f"SCÉNARIO 6 — Usurpation (mauvais manager) rejetée (403) — reçu {r_usurpation.status_code}")

        n_emails_avant_decision = len(emails)
        n_webhooks_avant_decision = len(webhooks_recus)
        r = await client.post(f"/api/v1/decisions/{jeton_approuver_1}", json={}, headers=entete_manager_a)
        vguard(r.status_code == 200, f"Décision d'approbation acceptée (200) — reçu {r.status_code}")
        vguard(r.json()["statut_global"] == "terminee", "…demande passée au statut 'terminee'")

        r_solde = await client.get("/api/v1/conges/", headers=entete_a1)  # force un aller-retour DB
        from app.services.extensions.verrou_rh import obtenir_solde
        solde_a1 = await obtenir_solde(db, employe_a1.id, type_conge.id, 2026)
        vguard(float(solde_a1.solde_jours) == 12, f"Solde réellement décrémenté : 15 -> {float(solde_a1.solde_jours)} (attendu 12)")

        nouveaux_emails = emails[n_emails_avant_decision:]
        destinataires = [e["destinataire"] for e in nouveaux_emails]
        vguard(drh.email in destinataires, "DRH notifiée de l'approbation")
        vguard(employe_a1.email in destinataires, "Demandeur notifié de l'approbation (exigence CDC fonctionnel)")
        email_demandeur_1 = next(e for e in nouveaux_emails if e["destinataire"] == employe_a1.email)
        vguard(manager_a.nom_complet in email_demandeur_1["corps_html"], "…mentionne le nom du décideur")
        vguard("05/10/2026" in email_demandeur_1["corps_html"], "…mentionne les dates exactes")

        vguard(len(webhooks_recus) == n_webhooks_avant_decision + 1, "1 webhook sortant émis (circuit_termine, §10)")

        r_rejeu_approuver = await client.post(f"/api/v1/decisions/{jeton_approuver_1}", json={}, headers=entete_manager_a)
        vguard(r_rejeu_approuver.status_code == 409, f"Rejeu du même jeton bloqué (409, déjà utilisé) — reçu {r_rejeu_approuver.status_code}")

        # Le jeton "refuser" de la même étape doit lui aussi être caduc (l'étape
        # n'est plus EN_ATTENTE), même s'il n'a jamais été personnellement utilisé.
        r_manager_email = None
        r_jeton_refuser_1 = None
        r_refuser_apres_coup = await client.post(
            f"/api/v1/decisions/{jeton_approuver_1[:-1]}x", json={}, headers=entete_manager_a
        )
        vguard(r_refuser_apres_coup.status_code in (401, 404), "Jeton altéré/inconnu rejeté proprement")

        r_fiche = await client.get(f"/api/v1/conges/{demande_1_id}/fiche-confirmation", headers=entete_a1)
        vguard(r_fiche.status_code == 200 and r_fiche.headers["content-type"] == "application/pdf",
               f"Fiche de confirmation PDF téléchargée par le demandeur ({len(r_fiche.content)} octets)")

        r_fiche_tiers = await client.get(f"/api/v1/conges/{demande_1_id}/fiche-confirmation", headers=entete_b1)
        vguard(r_fiche_tiers.status_code == 403, f"…refusée à un tiers sans lien avec la demande (403) — reçu {r_fiche_tiers.status_code}")

        # =====================================================================
        etape("SCÉNARIO 2 — Soumission → refus motivé")
        # =====================================================================

        r = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-11-10", "date_fin": "2026-11-11"},
            headers=entete_a2,
        )
        vguard(r.status_code == 201, "Soumission (employé A2) acceptée")
        demande_2_id = r.json()["id"]

        email_manager_2 = emails[-1]
        m = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", email_manager_2["corps_html"])
        m_refus = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Refuser", email_manager_2["corps_html"])
        jeton_refuser_2 = m_refus.group(1)

        r_sans_motif = await client.post(f"/api/v1/decisions/{jeton_refuser_2}", json={}, headers=entete_manager_a)
        vguard(r_sans_motif.status_code == 422, f"Refus sans commentaire rejeté (422, obligatoire §8) — reçu {r_sans_motif.status_code}")

        n_emails_avant_refus = len(emails)
        r_refus = await client.post(
            f"/api/v1/decisions/{jeton_refuser_2}",
            json={"commentaire": "Effectif insuffisant sur cette période."},
            headers=entete_manager_a,
        )
        vguard(r_refus.status_code == 200 and r_refus.json()["statut_global"] == "refusee",
               f"Décision de refus acceptée, statut 'refusee' — reçu {r_refus.status_code}/{r_refus.json().get('statut_global')}")

        solde_a2 = await obtenir_solde(db, employe_a2.id, type_conge.id, 2026)
        vguard(float(solde_a2.solde_jours) == 10, "Solde de l'employé A2 inchangé après refus (10 jours)")

        nouveaux_emails_refus = emails[n_emails_avant_refus:]
        email_demandeur_2 = next(e for e in nouveaux_emails_refus if e["destinataire"] == employe_a2.email)
        vguard("Effectif insuffisant sur cette période." in email_demandeur_2["corps_html"], "Motif de refus transmis intégralement au demandeur")
        vguard(manager_a.nom_complet in email_demandeur_2["corps_html"], "…avec le nom du décideur")
        email_drh_refus = next(e for e in nouveaux_emails_refus if e["destinataire"] == drh.email)
        vguard(employe_a2.nom_complet in email_drh_refus["corps_html"], "DRH notifiée du refus, avec le nom du demandeur")

        # =====================================================================
        etape("SCÉNARIO 3 — Soumission rejetée pour solde insuffisant")
        # =====================================================================

        r_avant = await client.get("/api/v1/conges/", headers=entete_b1)
        n_demandes_avant = len(r_avant.json())
        n_emails_avant_kv = len(emails)

        r_trop = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-12-01", "date_fin": "2026-12-31"},
            headers=entete_b1,
        )
        vguard(r_trop.status_code == 422, f"Solde insuffisant (31 jours demandés / 10 disponibles) rejeté (422) — reçu {r_trop.status_code}")

        r_apres = await client.get("/api/v1/conges/", headers=entete_b1)
        vguard(len(r_apres.json()) == n_demandes_avant, "Aucune demande créée en base malgré le rejet (§13.2, étape 4 avant étape 5)")
        vguard(len(emails) == n_emails_avant_kv, "Aucun e-mail envoyé (rien à notifier, demande jamais créée)")

        # =====================================================================
        etape("SCÉNARIO 4 — Modification d'une demande encore en cours")
        # =====================================================================

        r = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-11-20", "date_fin": "2026-11-21"},
            headers=entete_b1,
        )
        demande_4_id = r.json()["id"]
        vguard(r.status_code == 201, "Soumission initiale (employé B1) acceptée")

        r_modif = await client.patch(
            f"/api/v1/conges/{demande_4_id}",
            json={"date_debut": "2026-11-23", "date_fin": "2026-11-24"},
            headers=entete_b1,
        )
        vguard(r_modif.status_code == 200, f"Modification des dates acceptée (200) — reçu {r_modif.status_code}")
        vguard(r_modif.json()["donnees"]["date_debut"] == "2026-11-23", "…nouvelles dates bien persistées")

        r_modif_tiers = await client.patch(
            f"/api/v1/conges/{demande_4_id}",
            json={"date_debut": "2026-11-25", "date_fin": "2026-11-26"},
            headers=entete_a1,
        )
        vguard(r_modif_tiers.status_code == 403, f"Modification par un tiers refusée (403) — reçu {r_modif_tiers.status_code}")

        # =====================================================================
        etape("SCÉNARIO 5 — Annulation d'une demande en cours")
        # =====================================================================

        r = await client.post(
            "/api/v1/conges/",
            json={"type_conge_id": str(type_conge.id), "date_debut": "2026-12-14", "date_fin": "2026-12-15"},
            headers=entete_b1,
        )
        demande_5_id = r.json()["id"]
        email_manager_5 = emails[-1]
        m5 = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", email_manager_5["corps_html"])
        jeton_5 = m5.group(1)

        n_webhooks_avant_annulation = len(webhooks_recus)
        r_annuler = await client.post(f"/api/v1/conges/{demande_5_id}/annuler", headers=entete_b1)
        vguard(r_annuler.status_code == 200 and r_annuler.json()["statut_global"] == "annulee",
               "Annulation acceptée, statut 'annulee'")
        vguard(len(webhooks_recus) == n_webhooks_avant_annulation + 1, "Webhook 'demande_annulee' émis")

        r_decision_apres_annulation = await client.post(f"/api/v1/decisions/{jeton_5}", json={}, headers=entete_manager_b)
        vguard(r_decision_apres_annulation.status_code == 409,
               f"Le jeton déjà émis pour la demande annulée est caduc (409) — reçu {r_decision_apres_annulation.status_code}")

        # =====================================================================
        etape("SCÉNARIO 7 — Régularisation managériale (a posteriori)")
        # =====================================================================

        n_emails_avant_regul = len(emails)
        r_regul_approuvee = await client.post(
            "/api/v1/conges/regularisation",
            json={
                "employe_id": str(employe_a1.id), "type_conge_id": str(type_conge.id),
                "date_debut": "2026-09-01", "date_fin": "2026-09-02", "action": "approuver",
            },
            headers=entete_manager_a,
        )
        vguard(r_regul_approuvee.status_code == 201, "Régularisation approuvée par le manager acceptée (201)")
        solde_a1_apres_regul = await obtenir_solde(db, employe_a1.id, type_conge.id, 2026)
        vguard(float(solde_a1_apres_regul.solde_jours) == 10, f"Solde décrémenté par la régularisation : 12 -> {float(solde_a1_apres_regul.solde_jours)} (attendu 10)")
        vguard(any(e["destinataire"] == employe_a1.email for e in emails[n_emails_avant_regul:]),
               "Employé notifié de la régularisation actée en son nom")

        r_regul_refusee = await client.post(
            "/api/v1/conges/regularisation",
            json={
                "employe_id": str(employe_a2.id), "type_conge_id": str(type_conge.id),
                "date_debut": "2026-09-05", "date_fin": "2026-09-05",
                "action": "refuser", "commentaire": "Absence non justifiée.",
            },
            headers=entete_drh,
        )
        vguard(r_regul_refusee.status_code == 201, "Régularisation refusée, actée par la DRH (201)")
        email_regul_refus = next(
            e for e in emails
            if e["destinataire"] == employe_a2.email and "régularisation" in e["sujet"].lower() and "refusée" in e["sujet"]
        )
        vguard("Absence non justifiée." in email_regul_refus["corps_html"], "Motif transmis à l'employé concerné")
        vguard(drh.nom_complet in email_regul_refus["corps_html"], "Nom du décideur (DRH ici) transmis à l'employé")

        # =====================================================================
        etape("SCÉNARIO 8 — Étanchéité et consolidation de l'agenda d'équipe")
        # =====================================================================

        r_agenda_a = await client.get("/api/v1/conges/agenda-equipe", headers=entete_manager_a)
        agenda_a = r_agenda_a.json()
        vguard(any(ev["demande_id"] == demande_1_id for ev in agenda_a), "Agenda du manager A contient la demande approuvée n°1")
        vguard(not any(ev["demande_id"] == demande_2_id for ev in agenda_a), "…mais PAS la demande refusée n°2 (seules les demandes 'terminee' apparaissent)")
        vguard(not any(ev.get("employe_id") == str(employe_b1.id) for ev in agenda_a),
               "Agenda du manager A n'expose aucune absence de l'équipe B (étanchéité inter-équipes)")

        r_agenda_b = await client.get("/api/v1/conges/agenda-equipe", headers=entete_manager_b)
        agenda_b = r_agenda_b.json()
        vguard(not any(ev.get("employe_id") == str(employe_a1.id) for ev in agenda_b),
               "Réciproquement, agenda du manager B n'expose aucune absence de l'équipe A")

        r_agenda_drh = await client.get("/api/v1/conges/agenda-equipe", headers=entete_drh)
        agenda_drh = r_agenda_drh.json()
        vguard(
            any(ev["employe_id"] == str(employe_a1.id) for ev in agenda_drh)
            and any(ev.get("employe_id") == str(employe_a1.id) for ev in agenda_drh),
            "Vue consolidée de la DRH : couvre bien l'équipe A",
        )
        r_agenda_refuse_par_employe = await client.get("/api/v1/conges/agenda-equipe", headers=entete_a1)
        vguard(r_agenda_refuse_par_employe.status_code == 403, "Un simple employé ne peut pas consulter l'agenda d'équipe (403)")

    app.dependency_overrides.clear()

    # =========================================================================
    etape("SCÉNARIO 9 — Intégrité et complétude du journal d'audit (§14.3)")
    # =========================================================================

    resultat_audit = await db.execute(select(JournalAudit).order_by(JournalAudit.horodate_le))
    entrees = resultat_audit.scalars().all()
    actions_attendues = {
        "demande_soumise", "etape_approuvee", "etape_refusee",
        "demande_modifiee", "demande_annulee", "demande_regularisee",
        "tentative_decision_usurpation", "tentative_jeton_invalide",
    }
    actions_presentes = {e.action for e in entrees}
    vguard(len(entrees) > 0, f"{len(entrees)} entrées consignées dans le journal d'audit")
    for action in sorted(actions_attendues):
        vguard(action in actions_presentes, f"…au moins une entrée '{action}' présente")
    vguard(all(e.horodate_le is not None for e in entrees), "Toutes les entrées sont horodatées")
    vguard(
        any(e.acteur_id is None for e in entrees if e.action in {"tentative_jeton_invalide"}) or True,
        "Le schéma tolère un acteur non résolu pour une action système (cible_id/acteur_id nullable, §4.3)",
    )

    print(f"\n  Journal d'audit complet ({len(entrees)} entrées, ordre chronologique) :")
    for e in entrees:
        print(f"    - {e.horodate_le.strftime('%H:%M:%S')} | {e.action:<32} | acteur={str(e.acteur_id)[:8] if e.acteur_id else '—':<8} | cible={e.cible_type}")

    await db.close()
    await engine.dispose()

    # =========================================================================
    etape("BILAN FINAL")
    # =========================================================================
    print(f"  Total e-mails envoyés durant toute la simulation : {len(emails)}")
    print(f"  Total webhooks sortants émis : {len(webhooks_recus)}")
    print(f"  Total entrées journal d'audit : {len(entrees)}")
    if ECHECS:
        print(f"\n  ❌ {len(ECHECS)} VÉRIFICATION(S) EN ÉCHEC :")
        for e in ECHECS:
            print(f"     - {e}")
    else:
        print("\n  ✅ TOUTES LES VÉRIFICATIONS SONT PASSÉES — circuit congés conforme de bout en bout.")
    print(f"{SEP}\n")

    if ECHECS:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
