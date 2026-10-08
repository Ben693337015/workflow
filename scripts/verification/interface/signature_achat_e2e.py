"""
SIGNATURE GRAPHIQUE de l'approbateur final d'un achat (Direction generale), dans un VRAI navigateur, puis dans le PDF.

Pour chaque largeur d'ecran (bureau et telephone) :
  - le signataire arrive par son lien ; « Signer » sans trace est bloque ;
  - il TRACE a la souris : l'encre doit tomber la ou le pointeur est passe (alignement pointeur / canvas, y compris
    quand le canvas est affiche plus petit que ses 360 px) ;
  - « Effacer » vide la zone et re-bloque ; il re-trace puis signe ;
  - le demandeur telecharge le bon de commande : l'image embarquee est le trace, avec la meme quantite d'encre.

    PYTHONPATH=../../.. UI_SUFFIXE=<suffixe> UI_LARGEUR=1332|390 UI_DPR=1|2|3 python3 signature_achat_e2e.py
"""
import base64
import io
import os
import subprocess
import sys
import tempfile
import uuid

import httpx

from harness import BASE, DRH, PWD, sync_playwright
from circuits_ui_e2e import B, OUT, compte, controle, echecs, entete, etape_active, ouvrir_lien, run, se_connecter
from PIL import Image

L = int(os.environ.get("UI_LARGEUR", "1332"))
H = 820 if L > 600 else 780
DPR = float(os.environ.get("UI_DPR", "1"))        # densite de pixels de l'ecran du signataire (2 = iPhone / Retina)

# Un « S » anguleux qui occupe la zone : points en FRACTIONS de la zone (independants de sa taille affichee).
TRACE = [(0.10, 0.25), (0.35, 0.20), (0.50, 0.50), (0.35, 0.80), (0.12, 0.75)]


def encre(image: Image.Image) -> int:
    """Nombre de pixels visibles (alpha > 0) du PNG."""
    return sum(1 for a in image.convert("RGBA").getchannel("A").getdata() if a > 0)


def tracer(page, fractions):
    """Souris reelle : appui, deplacements fractionnes (evenements pointeur), relachement."""
    b = page.locator("canvas").first.bounding_box()
    pts = [(b["x"] + f[0] * b["width"], b["y"] + f[1] * b["height"]) for f in fractions]
    page.mouse.move(*pts[0])
    page.mouse.down()
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for i in range(1, 9):
            page.mouse.move(x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8)
    page.mouse.up()
    return b


def lire_canvas(page):
    """(png_base64, largeur_interne, largeur_affichee) du canvas."""
    return page.evaluate("""() => { const c = document.querySelector('canvas');
        return [c.toDataURL('image/png').split(',')[1], c.width, c.getBoundingClientRect().width]; }""")


def encre_autour(png_b64, x_frac, y_frac, rayon=6):
    """Encre dans le voisinage (en pixels INTERNES) du point (x_frac, y_frac) de la zone."""
    im = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    cx, cy = round(x_frac * im.width), round(y_frac * im.height)
    a = im.getchannel("A")
    return sum(1 for x in range(max(0, cx - rayon), min(im.width, cx + rayon + 1))
               for y in range(max(0, cy - rayon), min(im.height, cy + rayon + 1)) if a.getpixel((x, y)) > 0)


def main():
    marque = uuid.uuid4().hex[:6]
    service = f"SIG-{marque}"
    with httpx.Client(timeout=60) as c:
        h = entete(c, DRH)
        emp, _ = compte(c, h, "employe", service, "Employe Signature")
        c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=h,
              json={"service": service, "exercice": 2026, "budget_alloue": 50000}).raise_for_status()

    with sync_playwright() as p:
        nav = p.chromium.launch()
        d = nav.new_context(viewport={"width": L, "height": H}, accept_downloads=True).new_page()
        se_connecter(d, emp)
        print(f"\n== ACHAT -> signature graphique de la Direction generale ({L}px, densite {DPR:g}x)")
        d.goto(f"{BASE}/achats")
        d.wait_for_selector("#ach-tiers")
        d.fill("#ach-tiers", f"Fournisseur {marque}")
        d.fill("#ach-budget", "1800")
        d.fill("#ach-objet", "Maintenance annuelle")
        d.set_input_files("#ach-contrat", {"name": "contrat.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 c"})
        d.click("button:has-text(\"Soumettre la demande d'achat\")")
        d.locator("tr", has_text=f"Fournisseur {marque}").first.wait_for(timeout=15000)
        with httpx.Client(timeout=30) as c:
            aid = next(a["id"] for a in c.get(f"{B}/api/v1/achats/", headers=entete(c, emp)).json()
                       if a["donnees"]["tiers"] == f"Fournisseur {marque}")

        # avis juridique par l'API (le circuit n'est pas l'objet de ce test)
        e1 = run(etape_active(aid))
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{B}/api/v1/decisions/{e1['jeton']}", json={}, headers=entete(c, e1["email"]))
            controle("avis juridique favorable (prealable)", r.status_code == 200, r.text)

        e2 = run(etape_active(aid))
        controle("la Direction generale doit SIGNER", e2["role_user"] == "direction_generale" and not e2["derog"], str(e2))
        dg = nav.new_context(viewport={"width": L, "height": H}, device_scale_factor=DPR).new_page()
        ouvrir_lien(dg, e2["jeton"], e2["email"])
        dg.wait_for_selector("canvas", timeout=5000) if dg.locator("canvas").count() else None

        # 1. pas de trace : l'interface bloque
        dg.click("button:has-text('Signer')")
        dg.wait_for_selector("canvas", timeout=5000)
        controle("« Signer » sans trace : bloque, la zone de signature apparait", dg.locator("text=Demande approuvée").count() == 0
                 and dg.locator("text=Document signé").count() == 0)
        controle("le bouton « Effacer » est inactif tant que rien n'est trace", dg.locator("button:has-text('Effacer')").is_disabled())
        dg.screenshot(path=f"{OUT}/sig_{L}_1_vide.png")

        # 2. trace a la souris : l'encre est ou le pointeur est passe
        b = tracer(dg, TRACE)
        png, interne, affichee = lire_canvas(dg)
        print(f"     canvas interne {interne}px, affiche {affichee:.0f}px")
        controle(f"RESOLUTION : le canvas compte {round(360 * min(DPR, 3))} px internes pour une densite {DPR:g}x",
                 interne == round(360 * min(DPR, 3)), f"{interne}px")
        controle("la zone n'est pas vide apres le trace", encre(Image.open(io.BytesIO(base64.b64decode(png)))) > 50)
        controle("le texte confirme « Signature enregistrée »", dg.locator("text=Signature enregistrée").count() == 1)
        alignes = [encre_autour(png, fx, fy) for fx, fy in TRACE]
        controle("ALIGNEMENT : de l'encre sous CHAQUE point ou le pointeur est passe", all(n > 0 for n in alignes),
                 f"encre autour des points : {alignes} (canvas {interne}px affiche {affichee:.0f}px)")
        # un point loin du trace ne doit pas avoir d'encre
        controle("pas d'encre loin du trace (coin bas droit)", encre_autour(png, 0.92, 0.92) == 0)
        dg.screenshot(path=f"{OUT}/sig_{L}_2_trace.png")

        # 3. effacer puis re-tracer
        dg.click("button:has-text('Effacer')")
        png_vide, _, _ = lire_canvas(dg)
        controle("« Effacer » vide completement la zone", encre(Image.open(io.BytesIO(base64.b64decode(png_vide)))) == 0)
        dg.click("button:has-text('Signer')")
        controle("apres effacement : « Signer » est de nouveau bloque", dg.locator("text=Document signé").count() == 0)
        tracer(dg, TRACE)
        png_final, _, _ = lire_canvas(dg)
        encre_attendue = encre(Image.open(io.BytesIO(base64.b64decode(png_final))))
        controle("nouveau trace present", encre_attendue > 50)

        # 4. signature
        dg.click("button:has-text('Signer')")
        dg.wait_for_selector("text=Document signé", timeout=10000)
        controle("signature acceptee : « Document signé »", True)
        dg.screenshot(path=f"{OUT}/sig_{L}_3_signe.png")

        # 5. bon de commande : l'image du PDF est CE trace
        d.reload()
        ligne = d.locator("tr", has_text=f"Fournisseur {marque}").first
        ligne.wait_for(timeout=10000)
        with d.expect_download(timeout=30000) as dl:
            ligne.get_by_text("Bon de commande").first.click()
        pdf = open(dl.value.path(), "rb").read()
        controle("le demandeur telecharge un PDF", pdf[:4] == b"%PDF", dl.value.suggested_filename)
        with tempfile.TemporaryDirectory() as t:
            open(f"{t}/bc.pdf", "wb").write(pdf)
            subprocess.run(["pdfimages", "-png", f"{t}/bc.pdf", f"{t}/i"], check=True)
            images = [Image.open(f"{t}/{n}") for n in sorted(os.listdir(t)) if n.endswith(".png")]
            for im in images:
                im.load()
            tailles = [im.size for im in images]
            hauteur_interne = round(interne * 140 / 360)
            signatures = [im for im in images if im.size == (interne, hauteur_interne)]
            controle(f"le PDF embarque l'image a la resolution du pad ({interne} x {hauteur_interne})", bool(signatures), str(tailles))
            # l'image alpha (smask, niveaux de gris) porte le trace : meme quantite d'encre que le canvas
            masque = next((im for im in signatures if im.mode in ("L", "1")), None)
            if masque is not None:
                n = sum(1 for v in masque.getdata() if v > 0)
                controle(f"quantite d'encre du PDF = celle du canvas ({n} vs {encre_attendue})",
                         abs(n - encre_attendue) <= max(20, 0.05 * encre_attendue))
            controle("l'image embarquee n'est pas uniforme (un trace existe)",
                     any(len(set(im.convert('L').getdata())) > 1 for im in signatures))
            subprocess.run(["pdftoppm", "-r", "70", "-f", "1", "-l", "1", "-png", f"{t}/bc.pdf", f"{OUT}/sig_{L}_bc"], check=True)
        texte = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True).stdout.decode("utf-8", "ignore")
        controle("le bon indique « Signé électroniquement » par la Direction générale", "Signé électroniquement" in " ".join(texte.split()))
        nav.close()

    print("\n" + ("ECHECS : " + "; ".join(echecs) if echecs else "ECHECS : aucun"))
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
