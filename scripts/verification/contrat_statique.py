"""
Controle statique de la communication frontend -> backend : chaque appel de
frontend/src/lib/api.ts doit correspondre a une route reelle du backend
(OpenAPI) - chemin EXACT (slash final compris : les routes FastAPI y sont
sensibles) et methode. Ne demarre aucun serveur.

Usage (depuis la racine du depot, variables d'environnement de l'application
definies, ex. celles des tests) :  python scripts/verification/contrat_statique.py
"""
import json, os, re, sys
RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RACINE)
from app.main import app

openapi = app.openapi()
routes = {}  # (methode, chemin normalise) -> chemin reel
for chemin, ops in openapi["paths"].items():
    for methode in ops:
        routes[(methode.upper(), re.sub(r"\{[^}]+\}", "{p}", chemin))] = chemin

src = open(os.path.join(RACINE, "frontend/src/lib/api.ts"), encoding="utf-8").read()
blocs = re.split(r"\nexport (?:async )?function ", src)[1:]
appels, problemes = [], []
for bloc in blocs:
    nom = bloc.split("(")[0]
    # Requetes optionnelles ("${cond ? "?a=b" : ""}") : ce ne sont pas des segments de chemin.
    bloc = re.sub(r"\$\{[^}]*\?[^}]*\}", "", bloc)
    m = re.search(r"[`\"'}](/api/v1/[^`\"']*)[`\"']", bloc)
    if not m:
        continue
    chemin = m.group(1).split("?")[0]
    chemin = re.sub(r"\$\{[^}]+\}", "{p}", chemin)
    meth = re.search(r'method:\s*"(\w+)"', bloc)
    methode = meth.group(1) if meth else "GET"
    appels.append((nom, methode, chemin))
    if (methode, chemin) not in routes:
        # existe-t-il la meme route avec une autre methode / sans slash ?
        autres = [k for k in routes if k[1] == chemin]
        sans = [k for k in routes if k[1] == chemin.rstrip("/") or k[1] == chemin + "/"]
        problemes.append((nom, methode, chemin, autres, sans))

print(f"{len(appels)} appels analyses dans api.ts, {len(routes)} routes cote backend\n")
for nom, methode, chemin in appels:
    ok = (methode, chemin) in routes
    print(f"{'OK ' if ok else 'KO '} {methode:6} {chemin:60} ({nom})")
print()
if problemes:
    print("PROBLEMES :")
    for p in problemes:
        print(" ", p)
    sys.exit(1)
print("Aucun ecart de chemin ou de methode.")
