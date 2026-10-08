"""
Discussion demandeur <-> approbateur, de bout en bout, dans DEUX navigateurs independants (deux sessions).

    UI_PROCESSUS = conges | notes_frais | achats     (defaut conges)
    UI_LARGEUR   = largeur de fenetre en px           (defaut 1332 ; 390 = telephone)
    UI_TAILLE_MO = taille de la piece jointe en Mo    (defaut : petite piece ; ex. 25)

Scenario : le demandeur soumet -> l'APPROBATEUR REEL de l'etape (lu en base) ouvre son lien de decision SANS etre
connecte (cas de l'e-mail), se connecte, demande des precisions -> le demandeur ouvre la discussion depuis sa
liste -> echange dans les deux sens (rafraichissement automatique, sans recharger) avec une piece jointe que
l'approbateur telecharge -> reprise -> approbation.

Lancer (backend + frontend demarres, comptes verif-* crees) :
    export UI_SUFFIXE=<suffixe> DATABASE_URL=postgresql+asyncpg://workflows_app:apppass@localhost:5432/<base>
    PYTHONPATH=../../.. python3 discussion_e2e.py
Sort avec un code non nul si un controle echoue. Captures dans UI_SORTIE (defaut /tmp).
"""
import asyncio
import os
import sys
import uuid

import httpx
from sqlalchemy import select

from harness import BASE, EMP, DRH, PWD, SUF, login, sync_playwright
from app.core.database import AsyncSessionLocal
from app.models.etape_workflow import EtapeWorkflow
from app.models.user import Utilisateur
from app.services import decision_tokens

B = "http://localhost:8000"
OUT = os.environ.get("UI_SORTIE", "/tmp")
PROC = os.environ.get("UI_PROCESSUS", "conges")
L = int(os.environ.get("UI_LARGEUR", "1332"))
H = 679 if L > 600 else 740  # fenetre basse : c'est la que l'ancien panneau sortait de l'ecran
MOBILE = L <= 600
echecs = []
TAILLE_PIECE_MO = int(os.environ.get("UI_TAILLE_MO", "0"))  # 0 = petite piece ; ex. 25 pour un gros fichier
if TAILLE_PIECE_MO:
    _n = TAILLE_PIECE_MO * 1024 * 1024
    PIECE = ("justificatif.pdf", (b"%PDF-1.4\n" + bytes(range(256)) * (_n // 256 + 1))[:_n], "application/pdf")
else:
    PIECE = ("justificatif.pdf", b"%PDF-1.4 piece de test", "application/pdf")


def controle(libelle, ok, detail=""):
    print(("  OK  " if ok else "  KO  ") + libelle + (f"  [{detail}]" if detail else ""))
    if not ok:
        echecs.append(libelle)


def entete(c, email):
    r = c.post(f"{B}/api/v1/auth/login", json={"email": email, "mot_de_passe": PWD})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def preparer():
    """Une demande neuve du processus choisi ; renvoie (id, marque, etape_id)."""
    marque = uuid.uuid4().hex[:6]
    with httpx.Client(timeout=30) as c:
        h_drh, h_emp = entete(c, DRH), entete(c, EMP)
        if PROC == "conges":
            tid = c.get(f"{B}/api/v1/types-conge/", headers=h_emp).json()[0]["id"]
            moi = c.get(f"{B}/api/v1/auth/me", headers=h_emp).json()
            c.put(f"{B}/api/v1/utilisateurs/{moi['id']}/soldes-conges", headers=h_drh,
                  json={"type_conge_id": tid, "exercice": 2027, "jours_acquis": 300}).raise_for_status()  # chaque passage en consomme 2
            r = c.post(f"{B}/api/v1/conges/", headers=h_emp, json={
                "type_conge_id": tid, "date_debut": "2027-09-06", "date_fin": "2027-09-07", "commentaire": f"disc-{marque}"})
        elif PROC == "notes_frais":
            r = c.post(f"{B}/api/v1/notes-frais/", headers=h_emp, json={
                "montant": 20, "categorie": f"Verif {marque}", "date_depense": "2026-10-01",
                "description": "test discussion", "devise": "EUR"})
        else:
            c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=h_drh,
                  json={"service": "Verif", "exercice": 2026, "budget_alloue": 50000}).raise_for_status()
            r = c.post(f"{B}/api/v1/achats/", headers=h_emp,
                       data={"tiers": f"Tiers {marque}", "objet": "test discussion", "budget_engage": "1500"},
                       files={"fichier_contrat": ("contrat.pdf", b"%PDF-1.4 contrat", "application/pdf")})
        r.raise_for_status()
        return r.json()["id"], marque, r.json()["premiere_etape_id"]


async def approbateur_et_jeton(etape_id):
    async with AsyncSessionLocal() as s:
        etape = await s.get(EtapeWorkflow, uuid.UUID(etape_id))
        u = await s.get(Utilisateur, etape.approbateur_attendu_id)
        action = "signer" if etape.role.value == "signataire" else "approuver"
        t = await decision_tokens.generer_jeton_decision(s, etape.id, action, u.id)
        await s.commit()
        return u.email, t


# --- ce que le demandeur voit selon le processus
PAGE = "/mes-demandes"  # depuis le 07/10, la liste des trois types vit ici (les pages-formulaires n'ont plus de liste)
TITRE = {"conges": "Congé du 2027-09-06 au 2027-09-07", "notes_frais": "Note de frais « Verif {m} » du 2026-10-01",
         "achats": "Demande d'achat — Tiers {m}"}[PROC]
MARQUE_LIGNE = lambda m: {"conges": f"disc-{m}", "notes_frais": f"Verif {m}", "achats": f"Tiers {m}"}[PROC]


def messages(page):
    return page.locator('ul[aria-label="Messages de la discussion"] li')


def attendre_message(page, texte, delai_ms=16000):
    """Le panneau se rafraichit tout seul toutes les 10 s : on attend, SANS recharger la page."""
    page.wait_for_selector(f'ul[aria-label="Messages de la discussion"] >> text={texte}', timeout=delai_ms)


def main():
    demande_id, m, etape_id = preparer()
    email_appr, jeton = asyncio.run(approbateur_et_jeton(etape_id))
    print(f"[{PROC} | {L}px] demande {demande_id[:8]} ({m}) - approbateur reel : {email_appr.split('-')[0]}")
    with sync_playwright() as p:
        nav = p.chromium.launch()
        appr = nav.new_context(viewport={"width": L, "height": H}, accept_downloads=True).new_page()
        emp = nav.new_context(viewport={"width": L, "height": H}).new_page()
        login(emp, EMP)

        print("1) L'approbateur ouvre son lien SANS etre connecte, se connecte, demande des precisions")
        appr.goto(f"{BASE}/decisions/{jeton}")
        appr.wait_for_selector("text=Vous devez vous connecter", timeout=10000)
        controle("sans session : la page demande de se connecter (pas d'erreur, pas de fuite)", True)
        appr.fill("input[type=email], input[name=email], #email", email_appr)
        appr.fill("input[type=password]", PWD)
        appr.click("button[type=submit]")
        appr.wait_for_selector("text=Un doute", timeout=15000)
        controle("apres connexion : retour sur la page de decision de CE lien", f"/decisions/{jeton}" in appr.url)
        appr.click("text=Un doute")
        appr.fill("#precisions", "Quel est le motif exact ?")
        appr.click("text=Suspendre et demander des précisions")
        appr.wait_for_selector("text=en attente de précisions", timeout=8000)
        try:
            attendre_message(appr, "Quel est le motif exact", 8000)
            controle("la page bascule sur la discussion et montre la question", True)
        except Exception:
            controle("la page bascule sur la discussion et montre la question", False)

        print("2) Le demandeur ouvre la discussion depuis sa liste")
        emp.goto(f"{BASE}{PAGE}")
        ligne = emp.locator("tr", has_text=MARQUE_LIGNE(m))
        ligne.first.wait_for(timeout=10000)
        controle("statut « Précisions demandées » visible", "Précisions demandées" in ligne.first.inner_text())
        ligne.first.get_by_text("Discussion").first.click()
        boite = emp.get_by_role("dialog")
        boite.wait_for(timeout=5000)
        emp.wait_for_timeout(600)
        box = boite.bounding_box()
        controle("la boite de dialogue est entierement dans la fenetre (visible sans defiler)",
                 box["y"] >= 0 and box["y"] + box["height"] <= H and box["x"] >= 0 and box["x"] + box["width"] <= L,
                 f"x={box['x']:.0f} y={box['y']:.0f} l={box['width']:.0f} h={box['height']:.0f} fenetre={L}x{H}")
        controle("le titre rappelle la demande concernee", TITRE.format(m=m) in boite.inner_text(), TITRE.format(m=m))
        emp.wait_for_selector("text=Quel est le motif exact", timeout=8000)
        controle("le demandeur voit la question de l'approbateur", True)
        emp.screenshot(path=f"{OUT}/disc_{PROC}_{L}_ouverte.png")

        print("3) Reponse + piece jointe -> l'approbateur la recoit SANS recharger et la telecharge")
        emp.fill(f"#message-{demande_id}", "Voici le justificatif.")
        emp.set_input_files(f"#piece-{demande_id}", {"name": PIECE[0], "mimeType": PIECE[2], "buffer": PIECE[1]})
        emp.click("button:has-text('Envoyer')")
        emp.wait_for_selector("ul[aria-label='Messages de la discussion'] >> text=Voici le justificatif", timeout=60000)
        controle("le message envoye apparait, marque « (vous) »", "(vous)" in messages(emp).last.inner_text())
        controle("la piece jointe est visible dans le message", messages(emp).last.get_by_text(PIECE[0]).count() == 1)
        controle("le champ de saisie est vide apres l'envoi", emp.input_value(f"#message-{demande_id}") == "")
        try:
            attendre_message(appr, "Voici le justificatif")
            controle("l'approbateur recoit la reponse automatiquement (< 16 s, sans rechargement)", True)
            with appr.expect_download(timeout=60000) as dl:
                messages(appr).last.get_by_text(PIECE[0]).click()
            octets = open(dl.value.path(), "rb").read()
            controle("l'approbateur telecharge la piece a l'identique", octets == PIECE[1] and dl.value.suggested_filename == PIECE[0])
        except Exception as e:
            controle("l'approbateur recoit la reponse et telecharge la piece", False, str(e)[:90])

        print("4) L'approbateur repond -> le demandeur la recoit SANS recharger")
        appr.fill(f"#message-{demande_id}", "Merci, je reprends la decision.")
        appr.click("button:has-text('Envoyer')")
        try:
            attendre_message(emp, "je reprends la decision")
            controle("le demandeur recoit la reponse automatiquement", True)
        except Exception:
            controle("le demandeur recoit la reponse automatiquement", False)
        emp.screenshot(path=f"{OUT}/disc_{PROC}_{L}_echange.png")
        controle("3 messages dans l'ordre chronologique", messages(emp).count() == 3)

        print("5) Reprise puis approbation")
        appr.click("button:has-text('Reprendre le workflow')")
        appr.wait_for_selector("button:has-text(\"Confirmer l'approbation\"), button:has-text('Signer')", timeout=8000)
        controle("apres la reprise, l'approbateur retrouve le formulaire de decision", True)
        if appr.locator("button:has-text('Signer')").count():  # etape de signature : pas dans ces scenarios
            controle("etape de signature non couverte ici", False)
        else:
            appr.click("button:has-text(\"Confirmer l'approbation\")")
            appr.wait_for_selector("text=Demande approuvée", timeout=8000)
            controle("la decision est enregistree", True)
        emp.keyboard.press("Escape")
        emp.reload()
        emp.locator("tr", has_text=MARQUE_LIGNE(m)).first.wait_for(timeout=10000)
        texte = emp.locator("tr", has_text=MARQUE_LIGNE(m)).first.inner_text()
        controle("le demandeur n'est plus en « Précisions demandées »", "Précisions demandées" not in texte)
        if PROC != "achats":  # les achats ont encore l'etape de signature apres le juridique
            controle("le demandeur voit « Approuvée »", "Approuvée" in texte)
        emp.screenshot(path=f"{OUT}/disc_{PROC}_{L}_final.png")
        nav.close()

    print("\nECHECS :", echecs if echecs else "aucun")
    sys.exit(1 if echecs else 0)


main()
