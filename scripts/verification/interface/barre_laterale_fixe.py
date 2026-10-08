import os
OUT = os.environ.get('UI_SORTIE', '/tmp')
import sys; sys.path.insert(0,__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from harness import *
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1332,"height":679}); page=ctx.new_page()
    login(page,EMP)
    page.goto(f"{BASE}/notes-frais"); page.wait_for_selector("text=Mes notes de frais"); page.wait_for_timeout(1000)
    mesure="""(()=>{const a=document.querySelector('aside').getBoundingClientRect();const m=document.querySelector('main');
      return {sidebar_top:Math.round(a.top),sidebar_bottom:Math.round(a.bottom),
              fenetre_scrollY:Math.round(window.scrollY),
              page_defile_dans_main:Math.round(m.scrollTop),main_hauteur_contenu:m.scrollHeight,main_hauteur_visible:m.clientHeight,
              user_menu_visible:(()=>{const u=document.querySelector('aside button[aria-label=\"Menu du profil\"]').getBoundingClientRect();return u.bottom<=window.innerHeight && u.top>=0})()}})()"""
    print("AVANT défilement :",page.evaluate(mesure))
    page.evaluate("document.querySelector('main').scrollTo({top: 99999})"); page.wait_for_timeout(400)
    print("APRÈS défilement :",page.evaluate(mesure))
    page.screenshot(path=OUT+"/apres_notes_frais.png")
    b.close()
