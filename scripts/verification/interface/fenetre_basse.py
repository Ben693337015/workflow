import os
OUT = os.environ.get('UI_SORTIE', '/tmp')
import sys; sys.path.insert(0,__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from harness import *
with sync_playwright() as p:
    b=p.chromium.launch()
    # 1) fenêtre très basse : la navigation défile, le menu utilisateur reste visible
    ctx=b.new_context(viewport={"width":1332,"height":260}); page=ctx.new_page(); login(page,DRH)
    page.goto(BASE+"/admin"); page.wait_for_timeout(1500)
    print("fenêtre 260px de haut (DRH, 8 liens) :", page.evaluate("""(()=>{const nav=document.querySelector('aside nav');const u=document.querySelector('aside button[aria-label="Menu du profil"]').getBoundingClientRect();
      return {nav_defile:nav.scrollHeight>nav.clientHeight, menu_utilisateur_visible:u.top>=0&&u.bottom<=window.innerHeight, sidebar_bas:Math.round(document.querySelector('aside').getBoundingClientRect().bottom)}})()"""))
    ctx.close()
    # 2) mobile : tiroir
    ctx=b.new_context(viewport={"width":390,"height":800}); page=ctx.new_page(); login(page,EMP)
    page.goto(BASE+"/mes-demandes"); page.wait_for_timeout(1500)
    page.click("header button"); page.wait_for_timeout(600); page.screenshot(path=OUT+"/mobile_tiroir.png")
    b.close()
