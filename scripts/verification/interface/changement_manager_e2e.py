"""
La DRH attribue puis change le manager d'un employe, dans de VRAIS navigateurs (DRH, employe, nouveau manager).

    UI_LARGEUR = 1332 (defaut) | 390 (telephone)
    export UI_SUFFIXE=<suffixe> DATABASE_URL=postgresql+asyncpg://...
    PYTHONPATH=../../.. python3 changement_manager_e2e.py
Verifie : colonne Manager, « Aucun manager », attribution, demande en cours transmise au nouveau manager (lien
decisionnel du nouveau manager fonctionnel, approbation, retour chez l'employe), refus d'une boucle hierarchique.
"""
import uuid

import httpx

from circuits_ui_e2e import (B, BASE, DRH, H, L, OUT, PWD, compte, controle, echecs, entete, etape_active,
                             ouvrir_lien, run, se_connecter)
from harness import sync_playwright


def main():
    marque = uuid.uuid4().hex[:6]
    service = f"MGR-{marque}"
    with httpx.Client(timeout=60) as c:
        h = entete(c, DRH)
        a_mail, a_id = compte(c, h, "manager", service, f"Alpha {marque}")
        b_mail, b_id = compte(c, h, "manager", service, f"Bravo {marque}")
        emp_nom = f"Employe {marque}"
        emp_mail, emp_id = compte(c, h, "employe", service, emp_nom)
        c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=h,
              json={"service": service, "exercice": 2026, "budget_alloue": 100000}).raise_for_status()

    with sync_playwright() as p:
        nav = p.chromium.launch()
        drh = nav.new_context(viewport={"width": L, "height": H}).new_page()
        se_connecter(drh, DRH)
        drh.goto(f"{BASE}/admin")
        drh.wait_for_selector(f"text={emp_nom}", timeout=15000)

        def ligne(nom):
            return drh.locator("tr", has_text=nom).first

        print(f"\n== Attribution d'un manager a un compte qui n'en a pas ({L}px)")
        controle("la colonne Manager signale « Aucun manager »", "Aucun manager" in ligne(emp_nom).inner_text())
        drh.screenshot(path=f"{OUT}/mgr_{L}_avant.png")
        drh.click(f"button[aria-label='Attribuer le manager de {emp_nom}']")
        sel = drh.get_by_label(f"Manager de {emp_nom}")
        options = sel.locator("option").all_inner_texts()
        controle("le sélecteur propose les managers actifs (pas les employes, pas l'employe lui-meme)",
                 any(f"Alpha {marque}" in o for o in options) and not any(emp_nom in o for o in options), str(options[:6]))
        sel.select_option(a_id)
        drh.click("button:has-text('Enregistrer')")
        drh.wait_for_selector(f"text=Manager de {emp_nom} : Alpha {marque}", timeout=10000)
        controle("message de confirmation affiche", True)
        drh.wait_for_timeout(800)
        controle("la ligne affiche le manager", f"Alpha {marque}" in ligne(emp_nom).inner_text())
        controle("le bouton propose desormais « Changer le manager »",
                 drh.locator(f"button[aria-label='Changer le manager de {emp_nom}']").count() == 1)

        print("\n== L'employe soumet une note de frais : elle part chez le manager attribue")
        emp = nav.new_context(viewport={"width": L, "height": H}).new_page()
        se_connecter(emp, emp_mail)
        emp.goto(f"{BASE}/notes-frais")
        emp.wait_for_selector("#nf-montant")
        emp.fill("#nf-montant", "80")
        emp.fill("#nf-categorie", f"Repas {marque}")
        emp.fill("#nf-date", "2026-10-01")
        emp.fill("#nf-description", "Repas client")
        emp.click("button:has-text('Soumettre la note de frais')")
        emp.locator("tr", has_text=f"Repas {marque}").first.wait_for(timeout=15000)
        controle("soumission acceptee (avant : refusee faute de manager)", True)
        with httpx.Client(timeout=30) as c:
            notes = c.get(f"{B}/api/v1/notes-frais/", headers=entete(c, emp_mail)).json()
        nid = next(n["id"] for n in notes if n["donnees"]["categorie"] == f"Repas {marque}")
        e = run(etape_active(nid))
        controle("l'approbateur attendu est le manager attribue (Alpha)", e["email"] == a_mail, str(e))

        print("\n== Changement de manager avec une demande en cours")
        drh.reload()
        drh.wait_for_selector(f"text={emp_nom}", timeout=15000)
        drh.click(f"button[aria-label='Changer le manager de {emp_nom}']")
        drh.get_by_label(f"Manager de {emp_nom}").select_option(b_id)
        drh.click("button:has-text('Enregistrer')")
        drh.wait_for_selector("text=1 demande en cours transmise au nouveau manager", timeout=10000)
        controle("le message annonce la demande en cours transmise", True)
        drh.screenshot(path=f"{OUT}/mgr_{L}_apres.png")
        e2 = run(etape_active(nid))
        controle("l'etape est maintenant chez le nouveau manager (Bravo)", e2["email"] == b_mail, str(e2))

        nouveau = nav.new_context(viewport={"width": L, "height": H}).new_page()
        ouvrir_lien(nouveau, e2["jeton"], b_mail)
        controle("le nouveau manager voit la demande de l'employe", emp_nom in nouveau.locator("body").inner_text())
        nouveau.click("button:has-text(\"Confirmer l'approbation\")") if nouveau.locator(
            "button:has-text(\"Confirmer l'approbation\")").count() else nouveau.click("button:has-text('Approuver')")
        nouveau.wait_for_selector("text=Demande approuvée", timeout=10000)
        controle("le nouveau manager approuve", True)
        emp.reload()
        emp.locator("tr", has_text=f"Repas {marque}").first.wait_for(timeout=10000)
        controle("l'employe voit sa note « Approuvée »", "Approuvée" in emp.locator("tr", has_text=f"Repas {marque}").first.inner_text())

        print("\n== Boucle hierarchique refusee")
        drh.reload()
        drh.wait_for_selector(f"text=Alpha {marque}", timeout=15000)
        drh.click(f"button[aria-label='Attribuer le manager de Alpha {marque}']")
        drh.get_by_label(f"Manager de Alpha {marque}").select_option(b_id)
        drh.click("button:has-text('Enregistrer')")
        drh.wait_for_selector(f"text=Manager de Alpha {marque} : Bravo {marque}", timeout=10000)
        drh.wait_for_timeout(600)
        drh.click(f"button[aria-label='Attribuer le manager de Bravo {marque}']")
        drh.get_by_label(f"Manager de Bravo {marque}").select_option(a_id)
        drh.click("button:has-text('Enregistrer')")
        drh.wait_for_selector("text=boucle", timeout=10000)
        controle("Bravo -> Alpha alors qu'Alpha depend de Bravo : refus explicite affiche", True)
        drh.screenshot(path=f"{OUT}/mgr_{L}_boucle.png")
        nav.close()

    print("\nECHECS :", echecs if echecs else "aucun")
    raise SystemExit(1 if echecs else 0)


if __name__ == "__main__":
    main()
