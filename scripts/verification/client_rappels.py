"""
Test REEL des rappels automatiques (CDC 2.4) contre un backend demarre par serveur_rappels.py :
soumet une note de frais, observe les rappels (numerotation, journal d'audit, bloc budget),
decide avec le lien recu dans le dernier rappel, puis verifie qu'aucun rappel ne suit.

Prerequis : base fraiche (migrations + scripts/seed_demo.py) et, dans les DEUX commandes,
memes variables d'environnement que le backend (dont DATABASE_URL). Usage :
    RAPPEL_FREQUENCE_HEURES=0.0006 RAPPEL_VERIFICATION_MINUTES=0.03 \
        python scripts/verification/serveur_rappels.py &
    E2E_DB=/tmp/e2e.db python scripts/verification/client_rappels.py
"""
import json, re, sqlite3, time, urllib.request, urllib.error
B = "http://127.0.0.1:8001"
def appel(m, chemin, tok=None, corps=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request(B + chemin, json.dumps(corps).encode() if corps is not None else None, h, method=m)
    try:
        with urllib.request.urlopen(r, timeout=10) as x: return x.status, json.loads(x.read() or b"null")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"null")
def tok(e, p): return appel("POST", "/api/v1/auth/login", corps={"email": e, "mot_de_passe": p})[1]["access_token"]
def mails(): return [json.loads(l) for l in open("/tmp/mails.log")] if __import__("os").path.exists("/tmp/mails.log") else []
def rappels(): return [m for m in mails() if m["sujet"].startswith("Rappel")]
def audits(): return sqlite3.connect(__import__("os").environ.get("E2E_DB", "/tmp/e2e.db")).execute("select count(*) from journal_audit where action='rappel_automatique'").fetchone()[0]

drh, emp, man = tok("drh@demo.tld", "DrhPass123!"), tok("employe@demo.tld", "EmployePass123!"), tok("manager@demo.tld", "ManagerPass123!")
svc = appel("GET", "/api/v1/auth/me", emp)[1]["service"]
appel("PUT", "/api/v1/enveloppes-budgetaires/", drh, {"service": svc, "exercice": 2026, "budget_alloue": 10000})
c, nf = appel("POST", "/api/v1/notes-frais/", emp, {"montant": 120, "categorie": "Transport", "date_depense": "2026-03-01", "description": "Train"})
print("soumission note de frais:", c)
t0 = time.time(); time.sleep(8)
r = rappels()
print(f"apres {time.time()-t0:.0f}s : {len(r)} rappel(s) recu(s) par le manager, {audits()} entree(s) d'audit")
for m in r: print("  ->", m["to"], "|", m["sujet"])
nums = [int(re.search(r"n°(\d+)", m["sujet"]).group(1)) for m in r]
print("numerotation croissante sans doublon:", nums == list(range(1, len(nums) + 1)))
jetons = re.findall(r"/decisions/([A-Za-z0-9_\-]+)'", r[-1]["corps"])
print("liens du dernier rappel:", len(jetons), "| bloc budget present:", "Enveloppe suffisante" in r[-1]["corps"])
c, d = appel("POST", f"/api/v1/decisions/{jetons[0]}", man, {})
print("decision via le lien du rappel:", c, d.get("statut_global") if d else d)
n_avant = len(rappels()); time.sleep(5)
print(f"apres la decision : {len(rappels()) - n_avant} nouveau(x) rappel(s) (attendu : 0)")
