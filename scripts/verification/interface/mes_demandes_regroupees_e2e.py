"""
« Mes demandes » regroupe congés, notes de frais et achats ; /notes-frais et /achats ne gardent que leur formulaire.
Navigateur reel (bureau 1332 px puis mobile 390 px).   UI_SUFFIXE=<suffixe> python3 mes_demandes_regroupees_e2e.py
"""
import os, sys, uuid
import httpx
from playwright.sync_api import sync_playwright
from harness import BASE, EMP, PWD, login

OUT = os.environ.get("UI_SORTIE", "/tmp")
B = os.environ.get("UI_API", "http://localhost:8000")
echecs = []


def controle(libelle, ok, detail=""):
    print(("OK  " if ok else "KO  ") + libelle + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        echecs.append(libelle)


def preparer():
    """Garantit au moins une demande de chaque type pour l'employe de test."""
    marque = uuid.uuid4().hex[:6]
    with httpx.Client(timeout=30) as c:
        h = {"Authorization": "Bearer " + c.post(f"{B}/api/v1/auth/login", json={"email": EMP, "mot_de_passe": PWD}).json()["access_token"]}
        tid = c.get(f"{B}/api/v1/types-conge/").json()[0]["id"]
        c.post(f"{B}/api/v1/conges/", headers=h, json={"type_conge_id": tid, "date_debut": "2027-03-01", "date_fin": "2027-03-02", "commentaire": f"reg-{marque}"})
        n = c.post(f"{B}/api/v1/notes-frais/", headers=h, json={"montant": 33, "categorie": f"Reg {marque}", "date_depense": "2026-10-01", "description": "x"})
        if n.status_code == 201:
            c.post(f"{B}/api/v1/demandes/{n.json()['id']}/pieces-jointes", headers=h, files={"fichier": ("recu.pdf", b"%PDF-1.4 r", "application/pdf")})
        c.post(f"{B}/api/v1/achats/", headers=h, data={"tiers": f"Tiers reg {marque}", "objet": "o", "budget_engage": "90"},
               files={"fichier_contrat": ("c.pdf", b"%PDF-1.4 c", "application/pdf")})
    return marque


def verifier(pg, tag, largeur):
    pg.goto(f"{BASE}/mes-demandes")
    pg.wait_for_selector("[role=tablist]")
    pg.wait_for_selector("table")
    onglets = pg.locator("[role=tab]")
    noms = [" ".join(t.inner_text().split()) for t in onglets.all()]
    controle(f"{tag} : quatre onglets (Toutes + 3 types) avec compteur", len(noms) == 4 and all(any(ch.isdigit() for ch in n) for n in noms), str(noms))
    controle(f"{tag} : « Toutes » est selectionne au depart", onglets.first.get_attribute("aria-selected") == "true")
    corps = pg.inner_text("table")
    for type_ in ("Congé", "Note de frais", "Achat"):
        controle(f"{tag} : la pastille « {type_} » apparait dans la liste", type_ in corps)
    controle(f"{tag} : le statut reste distinct du type (pastilles « En cours »/« Approuvée »/… presentes)", any(s in corps for s in ("En cours", "Approuvée", "Refusée", "Signée")))
    pg.screenshot(path=f"{OUT}/mes_demandes_{tag}_toutes.png")

    pg.get_by_role("tab", name="Achats").click()
    lignes = pg.locator("tbody tr").all()
    textes = [l.inner_text() for l in lignes]
    controle(f"{tag} : filtre « Achats » : uniquement des achats", bool(textes) and all("Achat" in t and "Note de frais" not in t for t in textes), str(len(textes)))
    pg.screenshot(path=f"{OUT}/mes_demandes_{tag}_achats.png")
    pg.get_by_role("tab", name="Notes de frais").click()
    textes = [l.inner_text() for l in pg.locator("tbody tr").all()]
    controle(f"{tag} : filtre « Notes de frais » : uniquement des notes", bool(textes) and all("Note de frais" in t for t in textes))
    pg.get_by_role("tab", name="Congés").click()
    textes = [l.inner_text() for l in pg.locator("tbody tr").all()]
    controle(f"{tag} : filtre « Congés » : uniquement des congés", bool(textes) and all("Congé" in t for t in textes))
    controle(f"{tag} : pas de debordement horizontal de la page", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))

    # pages-formulaires : formulaire seul
    for chemin, champ, interdit in (("/notes-frais", "#nf-montant", "Mes notes de frais"), ("/achats", "#ach-tiers", "Mes demandes d'achat")):
        pg.goto(f"{BASE}{chemin}")
        pg.wait_for_selector(champ)
        pg.wait_for_timeout(500)
        controle(f"{tag} : {chemin} ne contient que le formulaire (pas de tableau)", pg.locator("table").count() == 0 and interdit not in pg.inner_text("body"))
        pg.screenshot(path=f"{OUT}/mes_demandes_{tag}_{chemin.strip('/')}.png")


def soumissions(pg, tag):
    marque = uuid.uuid4().hex[:5]
    pg.goto(f"{BASE}/notes-frais")
    pg.wait_for_selector("#nf-montant")
    pg.fill("#nf-montant", "21")
    pg.fill("#nf-categorie", f"Ui {marque}")
    pg.fill("#nf-date", "2026-10-01")
    pg.fill("#nf-description", "depuis le formulaire")
    pg.click("button:has-text('Soumettre la note de frais')")
    pg.wait_for_url("**/mes-demandes?type=notes_frais", timeout=15000)
    controle(f"{tag} : apres une note de frais : retour sur « Mes demandes », onglet Notes de frais",
             pg.get_by_role("tab", name="Notes de frais").get_attribute("aria-selected") == "true")
    pg.locator("tr", has_text=f"Ui {marque}").first.wait_for(timeout=10000)
    controle(f"{tag} : la nouvelle note est dans la liste, « En cours »", "En cours" in pg.locator("tr", has_text=f"Ui {marque}").first.inner_text())

    pg.goto(f"{BASE}/achats")
    pg.wait_for_selector("#ach-tiers")
    pg.fill("#ach-tiers", f"Achat Ui {marque}")
    pg.fill("#ach-budget", "55")
    pg.fill("#ach-objet", "depuis le formulaire")
    pg.set_input_files("#ach-contrat", {"name": "contrat.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 ui"})
    pg.click("button:has-text(\"Soumettre la demande d'achat\")")
    pg.wait_for_url("**/mes-demandes?type=achats", timeout=15000)
    controle(f"{tag} : apres un achat : onglet Achats", pg.get_by_role("tab", name="Achats").get_attribute("aria-selected") == "true")
    pg.locator("tr", has_text=f"Achat Ui {marque}").first.wait_for(timeout=10000)
    controle(f"{tag} : le nouvel achat est dans la liste", True)


preparer()
with sync_playwright() as p:
    nav = p.chromium.launch()
    for largeur, hauteur, tag in ((1332, 860, "bureau"), (390, 800, "mobile")):
        pg = nav.new_context(viewport={"width": largeur, "height": hauteur}).new_page()
        login(pg, EMP)
        print(f"\n== {tag} ({largeur}px)")
        verifier(pg, tag, largeur)
        if tag == "bureau":
            soumissions(pg, tag)
        pg.context.close()
    nav.close()
print("\nECHECS :", echecs if echecs else "aucun")
sys.exit(1 if echecs else 0)
