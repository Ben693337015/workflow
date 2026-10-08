"""
NOTES DE FRAIS avec derogation budgetaire et ACHATS, dans de VRAIS navigateurs (un par acteur) :
demandeur -> approbateur(s) reel(s) via leur lien de decision -> retour chez le demandeur.

    UI_LARGEUR = 1332 (defaut) | 390 (telephone)
Chaque passage cree ses comptes et un service unique (enveloppe neuve). Lancer (backend + frontend demarres) :
    export UI_SUFFIXE=<suffixe> DATABASE_URL=postgresql+asyncpg://...
    PYTHONPATH=../../.. python3 circuits_ui_e2e.py
"""
import asyncio
import os
import sys
import uuid

import httpx
from sqlalchemy import select

from harness import BASE, DRH, PWD, SUF, sync_playwright
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.etape_workflow import EtapeWorkflow
from app.models.enums import StatutEtape
from app.models.user import Utilisateur
from app.services import decision_tokens

B = "http://localhost:8000"
OUT = os.environ.get("UI_SORTIE", "/tmp")
L = int(os.environ.get("UI_LARGEUR", "1332"))
H = 820 if L > 600 else 780
echecs = []


def controle(libelle, ok, detail=""):
    print(("  OK  " if ok else "  KO  ") + libelle + (f"  [{detail}]" if (detail and not ok) else ""))
    if not ok:
        echecs.append(libelle)


def entete(c, email):
    r = c.post(f"{B}/api/v1/auth/login", json={"email": email, "mot_de_passe": PWD})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


async def definir_mot_de_passe(email):
    async with AsyncSessionLocal() as s:
        u = (await s.execute(select(Utilisateur).where(Utilisateur.email == email))).scalar_one()
        u.mot_de_passe_hash = hash_password(PWD)
        await s.commit()


async def etape_active(demande_id):
    async with AsyncSessionLocal() as s:
        e = (await s.execute(select(EtapeWorkflow).where(
            EtapeWorkflow.demande_id == uuid.UUID(demande_id),
            EtapeWorkflow.statut.in_([StatutEtape.EN_ATTENTE, StatutEtape.EN_COURS])))).scalars().first()
        if e is None:
            return None
        u = await s.get(Utilisateur, e.approbateur_attendu_id)
        action = "signer" if e.role.value == "signataire" else "approuver"
        j = await decision_tokens.generer_jeton_decision(s, e.id, action, u.id)
        await s.commit()
        return {"email": u.email, "jeton": j, "role_user": u.role.value, "derog": e.est_derogation}


def run(coro):
    """Execute une coroutine dans un thread a part : Playwright (API synchrone) occupe deja la boucle du thread
    principal. Le moteur est libere apres chaque appel (une connexion asyncpg appartient a sa boucle)."""
    from concurrent.futures import ThreadPoolExecutor
    from app.core.database import engine

    async def enveloppe():
        try:
            return await coro
        finally:
            await engine.dispose()

    with ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(enveloppe())).result()


def compte(c, h, role, service, nom, manager_id=None):
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post(f"{B}/api/v1/utilisateurs/", headers=h, json={
        "email": email, "nom_complet": nom, "service": service, "role": role, "manager_id": manager_id})
    assert r.status_code == 201, r.text
    run(definir_mot_de_passe(email))
    return email, r.json()["id"]


def se_connecter(page, email):
    page.goto(f"{BASE}/login")
    page.wait_for_selector("input[type=email], #email")
    page.fill("input[type=email], #email", email)
    page.fill("input[type=password]", PWD)
    page.click("button[type=submit]")
    page.wait_for_url("**/mes-demandes", timeout=30000)


def ouvrir_lien(page, jeton, email):
    """Lien e-mail ouvert SANS session : connexion sur la page, retour sur ce lien."""
    page.goto(f"{BASE}/decisions/{jeton}")
    page.wait_for_selector("text=Vous devez vous connecter", timeout=10000)
    page.fill("input[type=email], #email", email)
    page.fill("input[type=password]", PWD)
    page.click("button[type=submit]")
    page.wait_for_selector("text=Demande de", timeout=15000)


def dessiner_signature(page):
    cv = page.locator("canvas").first
    b = cv.bounding_box()
    page.mouse.move(b["x"] + 20, b["y"] + b["height"] / 2)
    page.mouse.down()
    for i in range(1, 12):
        page.mouse.move(b["x"] + 20 + i * 12, b["y"] + b["height"] / 2 + (18 if i % 2 else -18))
    page.mouse.up()


def main():
    marque = uuid.uuid4().hex[:6]
    service = f"UI-{marque}"
    with httpx.Client(timeout=60) as c:
        h = entete(c, DRH)
        mgr, mid = compte(c, h, "manager", service, "Manager UI")
        emp, _ = compte(c, h, "employe", service, "Employe UI", manager_id=mid)
        compte(c, h, "direction_financiere", service, "Direction financiere UI")
        c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=h,
              json={"service": service, "exercice": 2026, "budget_alloue": 100}).raise_for_status()

    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx_emp = nav.new_context(viewport={"width": L, "height": H}, accept_downloads=True)
        d = ctx_emp.new_page()
        se_connecter(d, emp)

        # ---------------------------------------------------------------- NOTE DE FRAIS EN DEROGATION
        print(f"\n== NOTE DE FRAIS en depassement budgetaire ({L}px)")
        d.goto(f"{BASE}/notes-frais")
        d.wait_for_selector("#nf-montant")
        d.fill("#nf-montant", "400")
        d.fill("#nf-categorie", f"Mission {marque}")
        d.fill("#nf-date", "2026-10-01")
        d.fill("#nf-description", "Deplacement client hors enveloppe")
        d.click("button:has-text('Soumettre la note de frais')")
        d.wait_for_selector("text=motif de dérogation", timeout=10000)
        controle("depassement sans motif : message clair affiche au demandeur", True)
        controle("la case de derogation est cochee automatiquement", d.is_checked("input[type=checkbox]"))
        controle("le champ « Motif de la dérogation » apparait", d.locator("#nf-motif").count() == 1)
        d.screenshot(path=f"{OUT}/circ_nf_{L}_motif_requis.png")
        d.fill("#nf-motif", "Mission client urgente, hors enveloppe")
        d.click("button:has-text('Soumettre la note de frais')")
        d.wait_for_selector("text=arbitrage exceptionnel (dérogation)", timeout=15000)
        controle("soumission acceptee : message « arbitrage exceptionnel »", True)
        ligne = d.locator("tr", has_text=f"Mission {marque}")
        ligne.first.wait_for(timeout=10000)
        controle("la note apparait dans la liste, statut « En cours »", "En cours" in ligne.first.inner_text())

        # recuperer l'etape reelle de cette note
        with httpx.Client(timeout=30) as c:
            notes = c.get(f"{B}/api/v1/notes-frais/", headers=entete(c, emp)).json()
        nid = next(n["id"] for n in notes if n["donnees"]["categorie"] == f"Mission {marque}")
        e = run(etape_active(nid))
        controle("l'etape cree est un arbitrage chez la Direction financiere (pas le manager)",
                 e["derog"] and e["role_user"] == "direction_financiere" and e["email"] != mgr, str(e))

        arb = nav.new_context(viewport={"width": L, "height": H}).new_page()
        ouvrir_lien(arb, e["jeton"], e["email"])
        txt = arb.locator("main, body").first.inner_text()
        controle("l'arbitre voit « Arbitrage exceptionnel »", "Arbitrage exceptionnel" in txt)
        controle("l'arbitre voit le motif du demandeur", "Motif de dérogation : Mission client urgente" in txt)
        controle("l'arbitre voit le montant en euros formate (400,00 €)", "400,00" in txt and "€" in txt)
        bloc = arb.get_by_role("group", name="Budget du service")
        controle("bloc budget : depassement de l'enveloppe en evidence", "Dépassement de l'enveloppe" in bloc.inner_text())
        arb.screenshot(path=f"{OUT}/circ_nf_{L}_arbitre.png")
        arb.click("button:has-text(\"Confirmer l'approbation\")")
        arb.wait_for_selector("text=justification d'acceptation est obligatoire", timeout=5000)
        controle("sans justification : l'interface bloque et l'explique", True)
        arb.fill("#justification", "Client strategique, accord de la direction")
        arb.click("button:has-text(\"Confirmer l'approbation\")")
        arb.wait_for_selector("text=Demande approuvée", timeout=10000)
        controle("avec justification : decision enregistree", True)
        arb.reload()
        arb.wait_for_timeout(2500)
        reouvert = arb.locator("body").inner_text()
        arb.screenshot(path=f"{OUT}/circ_nf_{L}_lien_rouvert.png")
        controle("le meme lien rouvert : message clair (deja traite / invalide), aucun formulaire de decision",
                 ("déjà" in reouvert or "invalide" in reouvert or "expiré" in reouvert) and arb.locator("button:has-text(\"Confirmer l'approbation\")").count() == 0,
                 reouvert[:200].replace("\n", " | "))

        d.reload()
        ligne = d.locator("tr", has_text=f"Mission {marque}")
        ligne.first.wait_for(timeout=10000)
        controle("le demandeur voit sa note « Approuvée »", "Approuvée" in ligne.first.inner_text())

        # ---------------------------------------------------------------- ACHAT (juridique puis DG signataire)
        print(f"\n== ACHAT : avis juridique puis signature de la Direction generale ({L}px)")
        with httpx.Client(timeout=30) as c:
            c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=entete(c, DRH),
                  json={"service": service, "exercice": 2026, "budget_alloue": 50000}).raise_for_status()
        d.goto(f"{BASE}/achats")
        d.wait_for_selector("#ach-tiers")
        d.fill("#ach-tiers", f"Fournisseur {marque}")
        d.fill("#ach-budget", "2500")
        d.fill("#ach-objet", "Licences logicielles")
        d.set_input_files("#ach-contrat", {"name": "contrat.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 contrat ui"})
        controle("le champ fichier affiche le nom choisi (en francais)", d.get_by_text("contrat.pdf").count() >= 1)
        d.click("button:has-text(\"Soumettre la demande d'achat\")")
        ligne = d.locator("tr", has_text=f"Fournisseur {marque}")
        ligne.first.wait_for(timeout=15000)
        controle("la demande d'achat apparait dans la liste du demandeur", True)
        with httpx.Client(timeout=30) as c:
            achats = c.get(f"{B}/api/v1/achats/", headers=entete(c, emp)).json()
        aid = next(a["id"] for a in achats if a["donnees"]["tiers"] == f"Fournisseur {marque}")

        e1 = run(etape_active(aid))
        controle("1re etape : SERVICE JURIDIQUE", e1["role_user"] == "service_juridique" and not e1["derog"], str(e1))
        jur = nav.new_context(viewport={"width": L, "height": H}).new_page()
        ouvrir_lien(jur, e1["jeton"], e1["email"])
        txt = " ".join(jur.locator("body").inner_text().split())  # espaces insecables normalises
        controle("le juriste voit le tiers, l'objet et le montant", f"Fournisseur {marque}" in txt and "Licences logicielles" in txt and "2 500,00" in txt.replace("\u202f", " ").replace("\u00a0", " "))
        controle("le juriste voit le contrat joint", "contrat.pdf" in txt)
        controle("pas de champ de justification (ce n'est pas une derogation)", jur.locator("#justification").count() == 0)
        jur.click("button:has-text(\"Confirmer l'approbation\")")
        jur.wait_for_selector("text=Demande approuvée", timeout=10000)
        controle("avis juridique favorable enregistre", True)

        e2 = run(etape_active(aid))
        controle("2e etape : DIRECTION GENERALE (signataire)", e2["role_user"] == "direction_generale", str(e2))
        dg = nav.new_context(viewport={"width": L, "height": H}).new_page()
        ouvrir_lien(dg, e2["jeton"], e2["email"])
        controle("le signataire voit un bouton « Signer » (et pas « Approuver »)", dg.locator("button:has-text('Signer')").count() == 1)
        dg.click("button:has-text('Signer')")
        dg.wait_for_selector("text=signature", timeout=5000)
        controle("sans signature : l'interface bloque", dg.locator("text=Demande approuvée").count() == 0)
        dessiner_signature(dg)
        dg.screenshot(path=f"{OUT}/circ_achat_{L}_signature.png")
        dg.click("button:has-text('Signer')")
        dg.screenshot(path=f"{OUT}/circ_achat_{L}_apres_signature.png")
        dg.wait_for_selector("text=Document signé", timeout=10000)
        controle("signature enregistree : achat valide", True)

        d.reload()
        ligne = d.locator("tr", has_text=f"Fournisseur {marque}")
        ligne.first.wait_for(timeout=10000)
        controle("le demandeur voit son achat « Signée »", "Signée" in ligne.first.inner_text(), ligne.first.inner_text()[:80])
        d.screenshot(path=f"{OUT}/circ_achat_{L}_liste.png")
        # bon de commande
        bouton = ligne.first.get_by_text("Bon de commande")
        if bouton.count():
            with d.expect_download(timeout=30000) as dl:
                bouton.first.click()
            octets = open(dl.value.path(), "rb").read()
            controle("le demandeur telecharge le bon de commande (PDF)", octets[:4] == b"%PDF", dl.value.suggested_filename)
        else:
            controle("lien « Bon de commande » present pour le demandeur", False)
        nav.close()

    print("\n" + ("ECHECS : " + "; ".join(echecs) if echecs else "ECHECS : aucun"))
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
