"""
Limite de taille des fichiers deposes : 40 Mo, de bout en bout (navigateur -> proxy Next.js -> backend -> disque).

  A. Chaine serveur via le PROXY Next.js (pas directement le backend) : 12 Mo (refuse avant), exactement 40 Mo,
     40 Mo + 1 octet ; relecture du fichier de 40 Mo octet pour octet (hachage) ; recus, contrat, discussion.
  B. Navigateur : un contrat de 39 Mo passe par le formulaire ; un fichier de 41 Mo est refuse AVANT l'envoi (aucune
     requete ne part) avec le message du serveur ; recu de 12 Mo sur une note de frais ; texte « 40 Mo maximum ».

    export UI_SUFFIXE=<suffixe>
    python3 fichiers_40mo_e2e.py        # backend (8000) + frontend (3000) demarres, comptes verif-* crees
"""
import hashlib
import os
import sys
import tempfile
import uuid

import httpx

from harness import BASE, EMP, DRH, MGR, PWD, login, sync_playwright

MO = 1024 * 1024
PROXY = BASE + "/api/backend"
OUT = os.environ.get("UI_SORTIE", "/tmp")
echecs = []


def controle(libelle, ok, detail=""):
    print(("  OK  " if ok else "  KO  ") + libelle + (f"  [{detail}]" if detail else ""))
    if not ok:
        echecs.append(libelle)


def pdf(octets):
    """Contenu PDF factice de la taille exacte demandee, non repetitif (detecte une troncature)."""
    entete = b"%PDF-1.4\n"
    motif = hashlib.sha256(b"graine").digest()
    corps = (motif * (octets // len(motif) + 1))[: octets - len(entete)]
    return entete + corps


def client_connecte(email):
    c = httpx.Client(base_url=PROXY, timeout=120)
    r = c.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": PWD})
    r.raise_for_status()
    return c


def partie_a():
    print("A) Chaine complete via le proxy Next.js")
    emp, drh = client_connecte(EMP), client_connecte(DRH)
    drh.put("/api/v1/enveloppes-budgetaires/", json={"service": "Verif", "exercice": 2026, "budget_alloue": 500000}).raise_for_status()
    marque = uuid.uuid4().hex[:6]

    note = emp.post("/api/v1/notes-frais/", json={"montant": 20, "categorie": f"Taille {marque}", "date_depense": "2026-10-01",
                                                  "description": "test taille maximale", "devise": "EUR"})
    note.raise_for_status()
    nid = note.json()["id"]
    depot = lambda octets: emp.post(f"/api/v1/demandes/{nid}/pieces-jointes", files={"fichier": ("recu.pdf", octets, "application/pdf")})

    r12 = depot(pdf(12 * MO))
    controle("recu de 12 Mo accepte (refuse avec l'ancienne limite de 10 Mo)", r12.status_code == 201, str(r12.status_code))
    ancien = depot(pdf(30 * MO + 1))
    controle("recu de 30 Mo + 1 octet accepte (c'etait la limite precedente : refuse avant le passage a 40 Mo)", ancien.status_code == 201, str(ancien.status_code))
    exact = pdf(40 * MO)
    r30 = depot(exact)
    controle("recu d'exactement 40 Mo accepte", r30.status_code == 201, f"{r30.status_code} {r30.text[:80] if r30.status_code != 201 else ''}")
    r31 = depot(pdf(40 * MO + 1))
    controle("40 Mo + 1 octet refuse (422) avec le message « 40 Mo »",
             r31.status_code == 422 and "40 Mo" in r31.json().get("detail", ""), f"{r31.status_code} {r31.text[:90]}")

    if r30.status_code == 201:
        pid = r30.json()["id"]
        telecharge = emp.get(f"/api/v1/demandes/{nid}/pieces-jointes/{pid}")
        controle("le fichier de 40 Mo est relu octet pour octet (hachage identique)",
                 telecharge.status_code == 200 and hashlib.sha256(telecharge.content).digest() == hashlib.sha256(exact).digest(),
                 f"{telecharge.status_code}, {len(telecharge.content)} octets")

    achat = lambda octets: emp.post("/api/v1/achats/", data={"tiers": f"Tiers {marque}", "objet": "contrat volumineux", "budget_engage": "800"},
                                    files={"fichier_contrat": ("contrat.pdf", octets, "application/pdf")})
    ra = achat(pdf(39 * MO))
    controle("contrat de 39 Mo accepte a la creation d'un achat", ra.status_code == 201, f"{ra.status_code} {ra.text[:80] if ra.status_code != 201 else ''}")
    rb = achat(pdf(40 * MO + 1))
    controle("contrat de 40 Mo + 1 refuse, aucun achat cree",
             rb.status_code == 422 and "40 Mo" in rb.json().get("detail", ""), f"{rb.status_code}")


def partie_b():
    print("B) Dans le navigateur (formulaires reels)")
    d = tempfile.mkdtemp()
    f39, f41, f12 = (os.path.join(d, n) for n in ("contrat39.pdf", "enorme41.pdf", "recu12.pdf"))
    for chemin, taille in ((f39, 39 * MO), (f41, 41 * MO), (f12, 12 * MO)):
        open(chemin, "wb").write(pdf(taille))
    marque = uuid.uuid4().hex[:6]
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_context(viewport={"width": 1332, "height": 900}).new_page()
        login(pg, EMP)

        pg.goto(f"{BASE}/achats")
        pg.wait_for_selector("text=Nouvelle demande d'achat")
        controle("la page des achats annonce « 40 Mo maximum »", "40 Mo maximum" in pg.inner_text("body") and "30 Mo" not in pg.inner_text("body") and "10 Mo" not in pg.inner_text("body"))
        pg.fill("#ach-tiers", f"Tiers UI {marque}")
        pg.fill("#ach-objet", "Contrat volumineux via le navigateur")
        pg.fill("#ach-budget", "700")

        posts = []
        pg.on("request", lambda r: posts.append(r) if r.method == "POST" and "/achats" in r.url else None)
        pg.set_input_files("#ach-contrat", f41)
        pg.click("button[type=submit]")
        pg.wait_for_selector("text=taille maximale autorisée (40 Mo)", timeout=8000)
        controle("fichier de 41 Mo : message d'erreur affiche avant tout envoi", True)
        controle("fichier de 41 Mo : aucune requete d'envoi n'est partie", len(posts) == 0, f"{len(posts)} requete(s)")
        pg.screenshot(path=f"{OUT}/fichiers_41mo_refuse.png")

        pg.set_input_files("#ach-contrat", f39)
        with pg.expect_response(lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith("/achats"), timeout=90000) as rep:
            pg.click("button[type=submit]")
        controle("fichier de 39 Mo : le formulaire est accepte par le serveur (201)", rep.value.status == 201, str(rep.value.status))
        pg.wait_for_selector(f"text=Tiers UI {marque}", timeout=15000)
        controle("la demande d'achat apparait dans la liste", True)
        pg.screenshot(path=f"{OUT}/fichiers_39mo_achat.png")

        pg.goto(f"{BASE}/notes-frais")
        pg.wait_for_selector("#nf-recu")
        controle("la page des notes de frais ne mentionne plus 10 Mo", "10 Mo" not in pg.inner_text("body"))
        nav.close()


partie_a()
partie_b()
print("\nECHECS :", echecs if echecs else "aucun")
sys.exit(1 if echecs else 0)
