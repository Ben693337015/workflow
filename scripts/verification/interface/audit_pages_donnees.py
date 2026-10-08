import os
OUT = os.environ.get('UI_SORTIE', '/tmp')
import sys, json; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from harness import *
import audit
JETON=open(OUT+"/jeton_B.txt").read().strip()
PAGES2 = {
  MGR: ["/agenda-equipe", "/regularisation", f"/decisions/{JETON}"],
  DRH: ["/synthese-frais", "/journal-audit", "/admin"],
  EMP: ["/mes-demandes", "/nouvelle-demande"],
}
res={}
with sync_playwright() as p:
    b=p.chromium.launch()
    for (w,h) in audit.VIEWPORTS:
        ctx=b.new_context(viewport={"width":w,"height":h}); page=ctx.new_page()
        for email,paths in PAGES2.items():
            ctx.clear_cookies(); page.goto(BASE+"/login"); page.evaluate("localStorage.clear()")
            login(page,email)
            for path in paths:
                page.goto(BASE+path); page.wait_for_timeout(1800)
                if path.startswith("/decisions/"):
                    page.screenshot(path=OUT+f"/decision_{w}.png", full_page=False)
                res[f"{w}|{path[:22]} [{email.split('-')[1]}]"]=page.evaluate(audit.JS)
        ctx.close()
    b.close()
json.dump(res,open(OUT+"/audit_pages2.json","w"),ensure_ascii=False,indent=1)
