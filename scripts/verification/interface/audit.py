import os
OUT = os.environ.get('UI_SORTIE', '/tmp')
import sys, json; sys.path.insert(0,__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from harness import *

JS = r"""
() => {
  const out = [];
  const vw = document.documentElement.clientWidth;
  const desc = el => {
    const cls = (el.className && typeof el.className === 'string') ? el.className.split(/\s+/).filter(Boolean).slice(0,3).join('.') : '';
    const t = (el.innerText || el.value || el.getAttribute('title') || '').replace(/\s+/g,' ').trim().slice(0,45);
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '') + (t ? ' «' + t + '»' : '');
  };
  const clipAncestor = el => { let p = el.parentElement; while (p) { const s = getComputedStyle(p); if (s.overflowX !== 'visible') return p; p = p.parentElement; } return null; };
  const hiddenAside = (() => { const a = document.querySelector('aside'); if (!a) return null; const r = a.getBoundingClientRect(); return r.right <= 1 ? a : null; })();
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (hiddenAside && hiddenAside.contains(el)) continue;
    if (el.closest('nextjs-portal, [data-nextjs-toast], [data-nextjs-dev-tools-button]')) continue;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const add = (type, extra) => { const k = type + desc(el); if (!seen.has(k)) { seen.add(k); out.push({type, el: desc(el), ...extra}); } };

    // A) tronque par un ancetre qui masque (overflow hidden/clip)
    const cl = clipAncestor(el);
    if (cl) {
      const cs = getComputedStyle(cl);
      const cr = cl.getBoundingClientRect();
      if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip') && r.right > cr.right + 1.5 && r.left < cr.right) {
        add('COUPÉ par un conteneur', {de: Math.round(r.right - cr.right), conteneur: desc(cl)});
      }
    }
    // B) texte tronque sur lui-meme
    if ((st.overflowX === 'hidden' || st.overflowX === 'clip') && el.scrollWidth > el.clientWidth + 1 && el.children.length === 0 && st.textOverflow !== 'ellipsis') {
      add('TEXTE TRONQUÉ sans ellipse', {de: el.scrollWidth - el.clientWidth});
    }
    // C) texte qui depasse de son parent (debordement visible)
    if (el.children.length === 0 && (el.textContent || '').trim().length > 0 && st.overflowX === 'visible') {
      const pr = el.parentElement.getBoundingClientRect();
      const range = document.createRange(); range.selectNodeContents(el);
      const tr = range.getBoundingClientRect();
      if (tr.right > pr.right + 1.5 && pr.width > 0) add('TEXTE DÉBORDE de son bloc', {de: Math.round(tr.right - pr.right)});
    }
    // D) hors ecran sans conteneur defilant
    if (r.right > vw + 1.5) {
      let p = el.parentElement, scroller = false;
      while (p) { const s = getComputedStyle(p); if (s.overflowX === 'auto' || s.overflowX === 'scroll') { scroller = true; break; } p = p.parentElement; }
      if (!scroller) add('HORS ÉCRAN', {de: Math.round(r.right - vw)});
    }
  }
  // E) defilements horizontaux
  const de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 1) out.push({type: 'DÉFILEMENT HORIZONTAL DE LA PAGE', el: 'html', de: de.scrollWidth - de.clientWidth});
  for (const el of document.querySelectorAll('main, main *')) {
    const s = getComputedStyle(el);
    if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1)
      out.push({type: 'défilement horizontal interne', el: desc(el), de: el.scrollWidth - el.clientWidth});
  }
  return out;
}
"""

PAGES = {
  EMP: ["/mes-demandes", "/nouvelle-demande", "/notes-frais", "/achats"],
  MGR: ["/regularisation", "/agenda-equipe", "/mes-demandes"],
  DRH: ["/admin", "/journal-audit", "/synthese-frais"],
}
VIEWPORTS = [(1332,679),(1024,700),(768,900),(390,800)]
ANON = ["/login", "/mot-de-passe-oublie"]

def run(label):
    resultats = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for (w,h) in VIEWPORTS:
            ctx = b.new_context(viewport={"width":w,"height":h}); page = ctx.new_page()
            for path in ANON:
                page.goto(BASE+path); page.wait_for_timeout(700)
                resultats[(w,path)] = page.evaluate(JS)
            for email, paths in PAGES.items():
                ctx.clear_cookies(); page.evaluate("localStorage.clear()")
                login(page, email)
                for path in paths:
                    page.goto(BASE+path); page.wait_for_timeout(1200)
                    resultats[(w,path+" ["+email.split('-')[1]+"]")] = page.evaluate(JS)
            ctx.close()
        b.close()
    return resultats

if __name__ == "__main__":
    res = run("")
    total = 0
    grouped = {}
    for (w,path),lst in res.items():
        for o in lst:
            if o["type"]=="défilement horizontal interne": continue
            grouped.setdefault((path,o["type"],o["el"]), []).append(w); total += 1
    print(f"OFFENSEURS (hors défilements internes volontaires) : {len(grouped)} distincts, {total} occurrences\n")
    for (path,t,el),ws in sorted(grouped.items()):
        print(f"[{path}] {t} — {el}  (largeurs: {sorted(set(ws))})")
    json.dump({f"{k[0]}|{k[1]}":v for k,v in res.items()}, open(sys.argv[1] if len(sys.argv)>1 else OUT+"/audit.json","w"), ensure_ascii=False, indent=1)
