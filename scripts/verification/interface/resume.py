import json,sys,collections,re
d=json.load(open(sys.argv[1]))
bad=collections.defaultdict(list); scroll=collections.defaultdict(list)
for key,lst in d.items():
    w,rest=key.split("|",1); path=rest
    for o in lst:
        if o["type"]=="défilement horizontal interne": scroll[(path,int(w))].append(o["de"])
        else: bad[(path,int(w))].append((o["type"],o["el"][:70],o.get("de")))
print("=== PROBLÈMES (coupé / tronqué sans ellipse / hors écran / déborde) ===")
if not bad: print("   aucun")
for (p,w),l in sorted(bad.items()):
    print(f" [{w}px] {p}: {len(l)}")
    for t,e,de in l[:4]: print(f"      - {t} | {e} | +{de}px")
print("\n=== Défilements horizontaux internes (le tableau défile dans son cadre) ===")
for (p,w),l in sorted(scroll.items()): print(f" [{w}px] {p}: {max(l)}px de défilement")
