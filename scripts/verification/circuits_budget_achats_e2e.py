"""
Verification de bout en bout (API reelle, base PostgreSQL reelle) des circuits :
  - NOTES DE FRAIS avec derogation budgetaire (arbitrage exceptionnel) et escalade au-dela du seuil ;
  - DEMANDES D'ACHAT (juridique -> Direction generale signataire) y compris derogation budgetaire.

Chaque passage cree ses propres comptes (service unique => enveloppe budgetaire neuve) : aucune dependance
a l'etat des passages precedents. Les approbateurs sont les VRAIS comptes (roles en base) ; les jetons de
decision sont generes comme le fait l'application (seul leur hash est stocke), puis utilises par la route
publique /api/v1/decisions/{jeton} avec la session du bon approbateur - exactement le chemin d'un clic e-mail.

Lancer (backend demarre) :
    export UI_SUFFIXE=<suffixe de verifier_corrections_postgres.py> DATABASE_URL=postgresql+asyncpg://...
    PYTHONPATH=../.. python3 circuits_budget_achats_e2e.py
Code de sortie non nul si un controle echoue.
"""
import asyncio
import base64
import os
import sys
import uuid

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.etape_workflow import EtapeWorkflow
from app.models.enums import StatutEtape
from app.models.user import Utilisateur
from app.services import decision_tokens

B = "http://localhost:8000"
PWD = "MotDePasseVerif123!"
SUF = os.environ["UI_SUFFIXE"]
DRH = f"verif-drh-{SUF}@example.com"
JUR = f"service_juridique-{SUF}@example.com"
DG = f"direction_generale-{SUF}@example.com"
SIGNATURE = base64.b64encode(
    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
).decode()
echecs: list[str] = []


def controle(libelle, ok, detail=""):
    print(("  OK  " if ok else "  KO  ") + libelle + (f"  [{detail}]" if (detail and not ok) else ""))
    if not ok:
        echecs.append(libelle)


def titre(t):
    print(f"\n== {t}")


def entete(c, email):
    r = c.post(f"{B}/api/v1/auth/login", json={"email": email, "mot_de_passe": PWD})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


async def _mot_de_passe(email):
    async with AsyncSessionLocal() as s:
        u = (await s.execute(select(Utilisateur).where(Utilisateur.email == email))).scalar_one()
        u.mot_de_passe_hash = hash_password(PWD)
        await s.commit()


async def _etape_active(demande_id):
    async with AsyncSessionLocal() as s:
        e = (await s.execute(select(EtapeWorkflow).where(
            EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.statut.in_([StatutEtape.EN_ATTENTE, StatutEtape.EN_COURS])
        ).order_by(EtapeWorkflow.niveau.desc()))).scalars().first()
        if e is None:
            return None
        u = await s.get(Utilisateur, e.approbateur_attendu_id)
        return {"id": e.id, "role": e.role.value, "niveau": e.niveau, "derog": e.est_derogation,
                "email": u.email, "role_user": u.role.value, "statut": e.statut.value}


async def _jeton(etape_id, action, approbateur_email):
    async with AsyncSessionLocal() as s:
        u = (await s.execute(select(Utilisateur).where(Utilisateur.email == approbateur_email))).scalar_one()
        j = await decision_tokens.generer_jeton_decision(s, etape_id, action, u.id)
        await s.commit()
        return j


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def creer_compte(c, h_drh, role, service, nom, manager_id=None):
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post(f"{B}/api/v1/utilisateurs/", headers=h_drh, json={
        "email": email, "nom_complet": nom, "service": service, "role": role, "manager_id": manager_id})
    assert r.status_code == 201, (role, r.status_code, r.text)
    run(_mot_de_passe(email))
    return email, r.json()["id"]


def decider(c, email, etape, action, **corps):
    """Decision par le chemin d'un clic e-mail : jeton + session de l'approbateur."""
    jeton = run(_jeton(etape["id"], action, email))
    return c.post(f"{B}/api/v1/decisions/{jeton}", headers=entete(c, email), json=corps)


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    marque = uuid.uuid4().hex[:6]
    service = f"Svc-{marque}"
    with httpx.Client(timeout=60) as c:
        h_drh = entete(c, DRH)
        # --- Comptes du service de test : un manager, un employe, et les arbitres necessaires.
        mgr_email, mgr_id = creer_compte(c, h_drh, "manager", service, "Manager Test")
        emp_email, _ = creer_compte(c, h_drh, "employe", service, "Employe Test", manager_id=mgr_id)
        cg_email, _ = creer_compte(c, h_drh, "controleur_de_gestion", service, "Controleur Test")
        df_email, _ = creer_compte(c, h_drh, "direction_financiere", service, "Direction Financiere Test")
        h_emp = entete(c, emp_email)
        # Les roles uniques ne sont pas garantis dans la base partagee : on resout le VRAI approbateur par etape.

        def enveloppe(budget):
            c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=h_drh,
                  json={"service": service, "exercice": 2026, "budget_alloue": budget}).raise_for_status()

        def env_etat():
            r = c.get(f"{B}/api/v1/enveloppes-budgetaires/", headers=h_drh).json()
            e = next(x for x in r if x["service"] == service and x["exercice"] == 2026)
            return e

        def note(montant, **extra):
            return c.post(f"{B}/api/v1/notes-frais/", headers=h_emp, json={
                "montant": montant, "categorie": f"Verif {marque}", "date_depense": "2026-10-01",
                "description": f"note {marque}", "devise": "EUR", **extra})

        # ================================================================== NOTES DE FRAIS
        titre("NOTES DE FRAIS - circuit standard (budget suffisant, sous le seuil)")
        enveloppe(5000)
        r = note(100)
        controle("soumission acceptee (201)", r.status_code == 201, r.text)
        d1 = r.json()
        controle("pas de derogation", d1["derogation"] is False)
        e = run(_etape_active(d1["id"]))
        controle("1re etape = le MANAGER du demandeur", e["email"] == mgr_email and not e["derog"], str(e))
        controle("le manager decide : approbation", (rr := decider(c, mgr_email, e, "approuver")).status_code == 200, rr.text)
        controle("demande terminee (sous le seuil : 1 seul niveau)", rr.json()["statut_global"] == "terminee")
        controle("budget consomme = 100", float(env_etat()["budget_consomme"]) == 100.0, str(env_etat()))

        titre("NOTES DE FRAIS - au-dela du seuil (500 EUR) : 2e niveau Direction financiere")
        r = note(800)
        d2 = r.json()
        e = run(_etape_active(d2["id"]))
        controle("niveau 1 = manager", e["email"] == mgr_email and e["niveau"] == 1)
        rr = decider(c, mgr_email, e, "approuver")
        controle("approbation manager : demande toujours en cours", rr.status_code == 200 and rr.json()["statut_global"] == "en_cours", rr.text)
        e2 = run(_etape_active(d2["id"]))
        controle("niveau 2 = un compte DIRECTION FINANCIERE", e2 and e2["niveau"] == 2 and e2["role_user"] == "direction_financiere", str(e2))
        rr = decider(c, e2["email"], e2, "approuver")
        controle("Direction financiere approuve -> terminee", rr.status_code == 200 and rr.json()["statut_global"] == "terminee", rr.text)
        controle("budget consomme = 900 (100 + 800)", float(env_etat()["budget_consomme"]) == 900.0)

        titre("NOTES DE FRAIS - DEROGATION : regles de saisie")
        r = note(50, derogation_motivee=True)
        controle("derogation cochee SANS motif -> 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")
        enveloppe(1000)  # consomme 900 : reste 100
        r = note(300)
        controle("depassement budgetaire SANS motif -> 422 (message clair)", r.status_code == 422 and "motif" in r.text.lower(), r.text[:160])
        n_avant = len(c.get(f"{B}/api/v1/notes-frais/", headers=h_emp).json())

        titre("NOTES DE FRAIS - DEROGATION par depassement : le flux est detourne vers l'arbitre")
        r = note(300, motif_derogation="Mission client urgente, hors enveloppe")
        controle("soumission acceptee malgre le depassement (201)", r.status_code == 201, r.text)
        d3 = r.json()
        controle("derogation detectee automatiquement", d3["derogation"] is True)
        controle("1 seule note creee en plus", len(c.get(f"{B}/api/v1/notes-frais/", headers=h_emp).json()) == n_avant + 1)
        e = run(_etape_active(d3["id"]))
        controle("l'etape est un ARBITRAGE (est_derogation) et non le manager",
                 e["derog"] and e["email"] != mgr_email and e["role_user"] in ("direction_financiere",), str(e))
        arb = e["email"]
        # Apercu cote approbateur (ce que voit la page de decision)
        jeton_prev = run(_jeton(e["id"], "approuver", arb))
        pv = c.get(f"{B}/api/v1/decisions/{jeton_prev}").json()
        controle("apercu : est_derogation = vrai", pv["est_derogation"] is True)
        controle("apercu : le motif du demandeur est visible", "Mission client urgente" in str(pv["resume"]), str(pv["resume"]))
        controle("apercu : budget en depassement affiche", pv["budget"] and pv["budget"]["solde_apres_validation"] < 0, str(pv["budget"]))
        controle("apercu : nom du demandeur", pv["demandeur_nom"] == "Employe Test")
        # Controles de securite
        autre = c.post(f"{B}/api/v1/decisions/{jeton_prev}", headers=entete(c, mgr_email), json={"justification_acceptation": "x"})
        controle("le MANAGER ne peut pas decider a la place de l'arbitre (403)", autre.status_code == 403, f"{autre.status_code}")
        # jeton consomme par la tentative ci-dessus ? (verifier_et_consommer ne consomme qu'a la decision)
        e = run(_etape_active(d3["id"]))
        r_sans = decider(c, arb, e, "approuver")
        controle("approuver SANS justification d'acceptation -> 422", r_sans.status_code == 422, f"{r_sans.status_code} {r_sans.text[:120]}")
        e = run(_etape_active(d3["id"]))
        controle("l'etape reste en attente apres le refus de saisie", e is not None and e["statut"] == "en_attente")

        titre("NOTES DE FRAIS - DEROGATION : discussion demandeur <-> arbitre pendant l'arbitrage")
        sp = c.post(f"{B}/api/v1/demandes/{d3['id']}/suspendre", headers=entete(c, arb), json={"message": "Quel client ?"})
        controle("l'arbitre demande des precisions (201)", sp.status_code == 201, sp.text[:150])
        controle("statut = precisions demandees",
                 any(x["id"] == d3["id"] and x["statut_global"] == "complement_demande" for x in c.get(f"{B}/api/v1/notes-frais/", headers=h_emp).json()))
        rm = c.post(f"{B}/api/v1/demandes/{d3['id']}/messages", headers=h_emp, json={"contenu": "Client ACME, contrat 2026-14"})
        controle("le demandeur repond (201)", rm.status_code == 201, rm.text[:150])
        msgs = c.get(f"{B}/api/v1/demandes/{d3['id']}/messages", headers=entete(c, arb)).json()
        controle("l'arbitre voit les 2 messages dans l'ordre", [m["contenu"] for m in msgs][-2:] == ["Quel client ?", "Client ACME, contrat 2026-14"], str(msgs))
        rp = c.post(f"{B}/api/v1/demandes/{d3['id']}/reprendre", headers=entete(c, arb))
        controle("l'arbitre reprend le workflow (200)", rp.status_code == 200, rp.text[:150])
        e = run(_etape_active(d3["id"]))
        rr = decider(c, arb, e, "approuver", justification_acceptation="Client strategique, accord DG")
        controle("approbation AVEC justification -> 200 et terminee", rr.status_code == 200 and rr.json()["statut_global"] == "terminee", rr.text[:150])
        controle("budget consomme = 1200 (le depassement est bien impute)", float(env_etat()["budget_consomme"]) == 1200.0, str(env_etat()))
        hist = c.get(f"{B}/api/v1/demandes/{d3['id']}/historique", headers=h_emp)
        txt = hist.text
        controle("historique du dossier accessible au demandeur", hist.status_code == 200, hist.text[:100])
        controle("historique : la derogation et la decision y figurent", "rogation" in txt and "Justification d'acceptation" in txt and "approuv" in txt.lower(), txt[:300])
        note_liste = next(x for x in c.get(f"{B}/api/v1/notes-frais/", headers=h_emp).json() if x["id"] == d3["id"])
        controle("le demandeur voit sa note 'terminee'", note_liste["statut_global"] == "terminee")

        titre("NOTES DE FRAIS - DEROGATION refusee")
        r = note(400, motif_derogation="Formation non budgetee")
        d4 = r.json()
        e = run(_etape_active(d4["id"]))
        controle("refus SANS commentaire -> 422", decider(c, e["email"], e, "refuser").status_code == 422)
        e = run(_etape_active(d4["id"]))
        rr = decider(c, e["email"], e, "refuser", commentaire="Hors budget, a reporter a T1")
        controle("refus avec commentaire -> refusee", rr.status_code == 200 and rr.json()["statut_global"] == "refusee", rr.text[:150])
        controle("budget NON consomme par la derogation refusee", float(env_etat()["budget_consomme"]) == 1200.0)
        controle("le demandeur voit le statut 'refusee'", next(x for x in c.get(f"{B}/api/v1/notes-frais/", headers=h_emp).json() if x["id"] == d4["id"])["statut_global"] == "refusee")

        titre("NOTES DE FRAIS - derogation motivee cochee alors que le budget suffit")
        enveloppe(50000)
        r = note(20, derogation_motivee=True, motif_derogation="Arbitrage souhaite")
        d5 = r.json()
        e = run(_etape_active(d5["id"]))
        controle("meme detournement vers l'arbitrage", r.status_code == 201 and d5["derogation"] and e["derog"] and e["email"] != mgr_email, str(e))
        titre("NOTES DE FRAIS - annulation : les liens deviennent caducs")
        jeton_old = run(_jeton(e["id"], "approuver", e["email"]))
        ra = c.post(f"{B}/api/v1/notes-frais/{d5['id']}/annuler", headers=h_emp)
        controle("le demandeur annule (200)", ra.status_code == 200, ra.text[:100])
        rr = c.post(f"{B}/api/v1/decisions/{jeton_old}", headers=entete(c, e["email"]), json={"justification_acceptation": "x"})
        controle("le lien d'une demande annulee est refuse (409)", rr.status_code == 409, f"{rr.status_code} {rr.text[:100]}")

        # ================================================================== ACHATS
        def achat(budget, **extra):
            data = {"tiers": f"Tiers {marque}", "objet": f"Achat {marque}", "budget_engage": str(budget), **extra}
            return c.post(f"{B}/api/v1/achats/", headers=h_emp, data=data,
                          files={"fichier_contrat": ("contrat.pdf", b"%PDF-1.4 contrat de test", "application/pdf")})

        enveloppe(20000)
        base_conso = float(env_etat()["budget_consomme"])
        titre("ACHATS - circuit standard : Juridique puis Direction generale (signature)")
        r = achat(1500)
        controle("soumission acceptee (201)", r.status_code == 201, r.text[:200])
        a1 = r.json()
        controle("pas de derogation", a1["derogation"] is False)
        e = run(_etape_active(a1["id"]))
        controle("1re etape = SERVICE JURIDIQUE (avis)", e["role_user"] == "service_juridique" and e["niveau"] == 1 and not e["derog"], str(e))
        # le demandeur voit sa demande + le contrat telechargeable par lui
        la = c.get(f"{B}/api/v1/achats/", headers=h_emp).json()
        controle("la demande figure dans la liste du demandeur (statut en_cours)", any(x["id"] == a1["id"] and x["statut_global"] == "en_cours" for x in la))
        pj = c.get(f"{B}/api/v1/achats/{a1['id']}/piece-jointe", headers=h_emp)
        controle("le demandeur retelecharge son contrat (200, contenu identique)", pj.status_code == 200 and pj.content == b"%PDF-1.4 contrat de test", str(pj.status_code))
        pj_j = c.get(f"{B}/api/v1/achats/{a1['id']}/piece-jointe", headers=entete(c, e["email"]))
        controle("le juridique peut lire le contrat (200)", pj_j.status_code == 200, str(pj_j.status_code))
        # un tiers sans lien ne voit pas le contrat
        h_mgr = entete(c, mgr_email)
        pj_x = c.get(f"{B}/api/v1/achats/{a1['id']}/piece-jointe", headers=h_mgr)
        controle("un tiers (manager sans lien avec l'achat) n'accede pas au contrat (403/404)", pj_x.status_code in (403, 404), str(pj_x.status_code))
        jur = e["email"]
        rr = decider(c, jur, e, "approuver")
        controle("avis juridique favorable -> demande toujours en cours", rr.status_code == 200 and rr.json()["statut_global"] == "en_cours", rr.text[:150])
        e2 = run(_etape_active(a1["id"]))
        controle("2e etape = DIRECTION GENERALE, role SIGNATAIRE", e2["role_user"] == "direction_generale" and e2["role"] == "signataire" and e2["niveau"] == 2, str(e2))
        controle("le budget n'est PAS encore consomme (circuit non termine)", float(env_etat()["budget_consomme"]) == base_conso)
        # approuver (sans signer) impossible
        j_app = run(_jeton(e2["id"], "approuver", e2["email"]))
        rr = c.post(f"{B}/api/v1/decisions/{j_app}", headers=entete(c, e2["email"]), json={})
        controle("une simple 'approbation' est refusee pour un signataire (400)", rr.status_code == 400, f"{rr.status_code} {rr.text[:100]}")
        e2 = run(_etape_active(a1["id"]))
        controle("signature vide -> 422", decider(c, e2["email"], e2, "signer").status_code == 422)
        e2 = run(_etape_active(a1["id"]))
        rr = decider(c, e2["email"], e2, "signer", signature_image_base64=SIGNATURE)
        controle("signature valide -> terminee", rr.status_code == 200 and rr.json()["statut_global"] == "terminee", rr.text[:150])
        controle("budget consomme = +1500", float(env_etat()["budget_consomme"]) == base_conso + 1500.0, str(env_etat()))
        bc = c.get(f"{B}/api/v1/achats/{a1['id']}/bon-de-commande", headers=h_emp)
        controle("bon de commande telechargeable par le demandeur (PDF)", bc.status_code == 200 and bc.content[:4] == b"%PDF", f"{bc.status_code}")
        la = next(x for x in c.get(f"{B}/api/v1/achats/", headers=h_emp).json() if x["id"] == a1["id"])
        controle("la liste du demandeur montre 'terminee'", la["statut_global"] == "terminee")
        h = c.get(f"{B}/api/v1/demandes/{a1['id']}/historique", headers=h_emp).text.lower()
        controle("historique : avis juridique et signature tracables", "sign" in h and h.count("approuv") + h.count("sign") >= 2, h[:300])

        titre("ACHATS - refus par le juridique, puis par la Direction generale")
        a2 = achat(900).json()
        e = run(_etape_active(a2["id"]))
        controle("refus juridique SANS motif -> 422", decider(c, e["email"], e, "refuser").status_code == 422)
        e = run(_etape_active(a2["id"]))
        rr = decider(c, e["email"], e, "refuser", commentaire="Clause de resiliation non conforme")
        controle("refus juridique motive -> refusee (circuit clos)", rr.status_code == 200 and rr.json()["statut_global"] == "refusee", rr.text[:150])
        controle("aucune etape suivante creee apres un refus", run(_etape_active(a2["id"])) is None)
        a3 = achat(700).json()
        e = run(_etape_active(a3["id"]))
        decider(c, e["email"], e, "approuver")
        e2 = run(_etape_active(a3["id"]))
        rr = decider(c, e2["email"], e2, "refuser", commentaire="Pas dans la strategie 2026")
        controle("refus de la Direction generale -> refusee", rr.status_code == 200 and rr.json()["statut_global"] == "refusee", rr.text[:150])
        controle("budget inchange apres 2 refus", float(env_etat()["budget_consomme"]) == base_conso + 1500.0)
        controle("pas de bon de commande pour un achat refuse (404/409)",
                 c.get(f"{B}/api/v1/achats/{a3['id']}/bon-de-commande", headers=h_emp).status_code in (404, 409))

        titre("ACHATS - DEROGATION budgetaire")
        enveloppe(2000)  # consomme 1500 -> reste 500
        r = achat(3000)
        controle("depassement SANS motif -> 422", r.status_code == 422 and "motif" in r.text.lower(), r.text[:160])
        r = achat(3000, motif_derogation="Renouvellement licence critique")
        controle("avec motif -> accepte (201), derogation detectee", r.status_code == 201 and r.json()["derogation"] is True, r.text[:200])
        a4 = r.json()
        e = run(_etape_active(a4["id"]))
        controle("l'etape est un ARBITRAGE (pas le juridique)", e["derog"] and e["role_user"] in ("controleur_de_gestion", "direction_generale"), str(e))
        arb = e["email"]
        controle("sans justification -> 422", (x := decider(c, arb, e, "approuver")).status_code == 422, x.text[:120])
        e = run(_etape_active(a4["id"]))
        # discussion sur un achat en arbitrage
        sp = c.post(f"{B}/api/v1/demandes/{a4['id']}/suspendre", headers=entete(c, arb), json={"message": "Duree d'engagement ?"})
        controle("discussion : l'arbitre demande des precisions", sp.status_code == 201, sp.text[:150])
        controle("discussion : le demandeur repond", c.post(f"{B}/api/v1/demandes/{a4['id']}/messages", headers=h_emp, json={"contenu": "12 mois"}).status_code == 201)
        controle("discussion : reprise", c.post(f"{B}/api/v1/demandes/{a4['id']}/reprendre", headers=entete(c, arb)).status_code == 200)
        e = run(_etape_active(a4["id"]))
        action = "signer" if e["role"] == "signataire" else "approuver"
        corps = {"justification_acceptation": "Licence critique, accord de la DG"}
        if action == "signer":
            corps["signature_image_base64"] = SIGNATURE
        rr = decider(c, arb, e, action, **corps)
        controle("arbitre valide avec justification -> terminee", rr.status_code == 200 and rr.json()["statut_global"] == "terminee", rr.text[:200])
        controle("budget = +3000 (depassement impute)", float(env_etat()["budget_consomme"]) == base_conso + 1500.0 + 3000.0, str(env_etat()))
        bc = c.get(f"{B}/api/v1/achats/{a4['id']}/bon-de-commande", headers=h_emp)
        controle("bon de commande genere pour l'achat valide par derogation (PDF)", bc.status_code == 200 and bc.content[:4] == b"%PDF", f"{bc.status_code} {bc.text[:120] if bc.status_code != 200 else ''}")

        titre("ACHATS - usurpation, annulation")
        enveloppe(50000)
        a5 = achat(400).json()
        e = run(_etape_active(a5["id"]))
        jt = run(_jeton(e["id"], "approuver", e["email"]))
        rr = c.post(f"{B}/api/v1/decisions/{jt}", headers=h_emp, json={})
        controle("le demandeur ne peut pas approuver son propre achat (403)", rr.status_code == 403, f"{rr.status_code}")
        controle("annulation par le demandeur (200)", c.post(f"{B}/api/v1/achats/{a5['id']}/annuler", headers=h_emp).status_code == 200)
        rr = c.post(f"{B}/api/v1/decisions/{jt}", headers=entete(c, e["email"]), json={})
        controle("le lien d'un achat annule est refuse (409)", rr.status_code == 409, f"{rr.status_code}")

    print("\n" + ("ECHECS : " + "; ".join(echecs) if echecs else "ECHECS : aucun"))
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
