"""Bascule clair/sombre en vrai navigateur (bureau + 390 px) : clic, memorisation, persistance. UI_SUFFIXE=<suffixe> python3 bascule_theme_e2e.py"""
from playwright.sync_api import sync_playwright
BASE="http://localhost:3000"; PWD="MotDePasseVerif123!"; OUT="/tmp"
def bg(pg): return pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--page').trim()")
ok=True
def check(c,m):
    global ok; print(("OK  " if c else "KO  ")+m); ok&=bool(c)
with sync_playwright() as p:
    nav=p.chromium.launch()
    for w,h,tag in ((1332,820,"d"),(390,780,"m")):
        ctx=nav.new_context(viewport={"width":w,"height":h},color_scheme="dark"); pg=ctx.new_page()
        # login (bouton present aussi)
        pg.goto(f"{BASE}/login"); check(pg.locator("button[aria-label]").first.is_visible(),f"{tag} bouton sur /login")
        pg.fill("input[type=email]",f"verif-employe-{__import__('os').environ['UI_SUFFIXE']}@example.com"); pg.fill("input[type=password]",PWD); pg.click("button[type=submit]")
        pg.wait_for_url("**/mes-demandes",timeout=20000); pg.goto(f"{BASE}/nouvelle-demande"); pg.wait_for_timeout(1200)
        b=pg.locator("button[aria-label*='mode'], button[aria-label='Changer de thème']").filter(visible=True).first
        check(b.is_visible(),f"{tag} bouton visible"); box=b.bounding_box(); print("   position",box)
        check(bg(pg)=="#11162a",f"{tag} depart sombre (systeme) {bg(pg)}")
        check(b.get_attribute("aria-label")=="Passer en mode clair",f"{tag} libelle {b.get_attribute('aria-label')}")
        b.click(); pg.wait_for_timeout(300)
        check(bg(pg)=="#e7ebf2",f"{tag} apres clic clair {bg(pg)}")
        check(pg.evaluate("localStorage.getItem('theme')")=="light",f"{tag} memorise")
        pg.screenshot(path=f"{OUT}/bascule-{tag}-clair.png")
        pg.reload(); pg.wait_for_timeout(800)
        check(bg(pg)=="#e7ebf2",f"{tag} persiste apres rechargement")
        pg.goto(f"{BASE}/achats"); pg.wait_for_timeout(800); check(bg(pg)=="#e7ebf2",f"{tag} persiste sur une autre page")
        b=pg.locator("button[aria-label*='mode']").filter(visible=True).first; b.click(); pg.wait_for_timeout(300)
        check(bg(pg)=="#11162a",f"{tag} retour sombre")
        pg.screenshot(path=f"{OUT}/bascule-{tag}-sombre.png")
        # decalage: pas de debordement horizontal
        check(pg.evaluate("document.documentElement.scrollWidth<=innerWidth"),f"{tag} pas de debordement horizontal")
        ctx.close()
print("TOUT OK" if ok else "ECHEC")
