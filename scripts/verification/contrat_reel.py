"""
Parcours REEL a travers le proxy Next.js (frontend) jusqu'au backend, exactement
comme le frontend l'appelle. Chaque reponse JSON est comparee aux interfaces
TypeScript de frontend/src/types/index.ts : tout champ non optionnel declare
par le frontend doit etre present dans la reponse reelle du backend.
Aucune redirection n'est suivie : un 3xx est un echec.

Prerequis : base FRAICHE (migrations + scripts/seed_demo.py, memes variables
d'environnement que le backend, dont DATABASE_URL), backend et frontend
demarres. Usage :
    BASE=http://127.0.0.1:3001/api/backend python scripts/verification/contrat_reel.py
"""
import asyncio, json, os, re, sys, uuid, urllib.error, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
BASE = os.environ["BASE"]

# ---------- interfaces TypeScript (champs de premier niveau, optionnels reperes) ----------
src_types = open(f"{ROOT}/frontend/src/types/index.ts", encoding="utf-8").read()
INTERFACES = {}
for m in re.finditer(r"export interface (\w+) \{\n(.*?)\n\}", src_types, re.S):
    champs, profondeur = {}, 0
    for ligne in m.group(2).splitlines():
        s = ligne.strip()
        if profondeur == 0 and not s.startswith(("/", "*")):
            mm = re.match(r"(\w+)(\?)?:", s)
            if mm:
                champs[mm.group(1)] = bool(mm.group(2))
        profondeur += ligne.count("{") - ligne.count("}")
    INTERFACES[m.group(1)] = champs

# ---------- (methode, chemin) -> type de retour declare dans api.ts ----------
src_api = open(f"{ROOT}/frontend/src/lib/api.ts", encoding="utf-8").read()
TYPE_DE = {}
for bloc in re.split(r"\nexport (?:async )?function ", src_api)[1:]:
    bloc = re.sub(r"\$\{[^}]*\?[^}]*\}", "", bloc)
    mp = re.search(r"[`\"'}](/api/v1/[^`\"']*)[`\"']", bloc)
    mt = re.search(r"requete<(\w+)(\[\])?>", bloc) or re.search(r"Promise<(\w+)>", bloc)
    if mp and mt and mt.group(1) in INTERFACES:
        meth = re.search(r'method:\s*"(\w+)"', bloc)
        chemin = re.sub(r"\$\{[^}]+\}", "{p}", mp.group(1).split("?")[0])
        TYPE_DE[((meth.group(1) if meth else "GET"), chemin)] = (mt.group(1), mt.lastindex >= 2 and bool(mt.group(2)))

class SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
opener = urllib.request.build_opener(SansRedirection)

RESULTATS = []
def noter(label, ok, detail=""):
    RESULTATS.append(ok)
    print(f"{'OK ' if ok else 'KO '} {label}" + (f"  -- {detail}" if detail else ""))

def appel(methode, chemin, token=None, json_corps=None, brut=None, entetes=None, attendu=(200, 201)):
    h = dict(entetes or {})
    data = None
    if json_corps is not None:
        data = json.dumps(json_corps).encode(); h["Content-Type"] = "application/json"
    if brut is not None:
        data = brut
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + chemin, data=data, headers=h, method=methode)
    try:
        r = opener.open(req, timeout=15); code, corps = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, corps = e.code, e.read()
    try:
        parse = json.loads(corps)
    except Exception:
        parse = corps
    return code, parse

def norm(chemin_reel, modele):
    return modele

def verifier(label, methode, modele, code, corps, attendu=(200, 201)):
    if code not in attendu:
        noter(label, False, f"HTTP {code}: {str(corps)[:120]}")
        return False
    cle = (methode, modele)
    if cle not in TYPE_DE:
        noter(label, True, f"HTTP {code} (pas de type TS declare)")
        return True
    nom, liste = TYPE_DE[cle]
    element = corps[0] if (liste and isinstance(corps, list) and corps) else corps
    if liste and (not isinstance(corps, list)):
        noter(label, False, "liste attendue"); return False
    if liste and not corps:
        noter(label, True, f"HTTP {code}, liste vide (champs non verifiables)"); return True
    manquants = [c for c, opt in INTERFACES[nom].items() if not opt and c not in element]
    noter(label, not manquants, f"{nom}: " + (f"CHAMPS MANQUANTS {manquants}" if manquants else f"{len(INTERFACES[nom])} champs declares, tous presents"))
    return not manquants

def multipart(champs, nom_champ_fichier, nom_fichier, octets, type_mime="application/pdf"):
    """Corps multipart/form-data construit a la main (octets bruts preserves). Retourne (corps, content_type)."""
    fr = "----frontiere" + uuid.uuid4().hex
    corps = b"".join(
        f'--{fr}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in champs.items()
    )
    corps += (
        f'--{fr}\r\nContent-Disposition: form-data; name="{nom_champ_fichier}"; filename="{nom_fichier}"\r\n'
        f"Content-Type: {type_mime}\r\n\r\n"
    ).encode() + octets + f"\r\n--{fr}--\r\n".encode()
    return corps, f"multipart/form-data; boundary={fr}"


def login(email, mdp):
    code, corps = appel("POST", "/api/v1/auth/login", json_corps={"email": email, "mot_de_passe": mdp})
    verifier(f"login {email}", "POST", "/api/v1/auth/login", code, corps)
    return corps

def jeton_acces(utilisateur_id):
    """
    Jeton d'acces (Bearer) pour un utilisateur cree UNIQUEMENT via l'API d'administration
    (sans mot de passe active) : necessaire pour verifier en reel les routes authentifiees d'un
    role qui, dans ce parcours, n'a jamais complete le flux d'activation par e-mail.
    """
    from app.core.security import create_access_token
    return create_access_token(str(utilisateur_id))


async def etape_id_niveau(demande_id, niveau):
    """Identifiant de l'etape d'un niveau donne pour une demande (utilise pour verifier une escalade)."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings
    from app.models.etape_workflow import EtapeWorkflow

    moteur = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(moteur, expire_on_commit=False, class_=AsyncSession)() as db:
            resultat = await db.execute(
                select(EtapeWorkflow.id).where(
                    EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == niveau
                )
            )
            ligne = resultat.first()
            return str(ligne[0]) if ligne else None
    finally:
        await moteur.dispose()


async def jeton_decision(etape_id, action, approbateur_id):
    # Moteur ephemere par appel : un moteur asyncpg reutilise entre deux asyncio.run() echoue
    # ("attached to a different loop") - aiosqlite, lui, le tolere.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings
    from app.services import decision_tokens

    moteur = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(moteur, expire_on_commit=False, class_=AsyncSession)() as db:
            j = await decision_tokens.generer_jeton_decision(db, uuid.UUID(etape_id), action, uuid.UUID(approbateur_id))
            await db.commit()
            return j
    finally:
        await moteur.dispose()


def main():
    print(f"{len(INTERFACES)} interfaces TS, {len(TYPE_DE)} appels api.ts types\n")
    drh, emp, man = (login("drh@demo.tld", "DrhPass123!"), login("employe@demo.tld", "EmployePass123!"), login("manager@demo.tld", "ManagerPass123!"))
    T_DRH, T_EMP, T_MAN = drh["access_token"], emp["access_token"], man["access_token"]

    # --- session ---
    c, moi = appel("GET", "/api/v1/auth/me", T_EMP)
    verifier("auth/me", "GET", "/api/v1/auth/me", c, moi)
    c, r = appel("POST", "/api/v1/auth/refresh", json_corps={"refresh_token": emp["refresh_token"]})
    verifier("auth/refresh (contrat TokenResponse)", "POST", "/api/v1/auth/login", c, r)
    if c == 200:
        c2, _ = appel("GET", "/api/v1/auth/me", r["access_token"])
        noter("le NOUVEAU jeton d'acces obtenu par refresh fonctionne", c2 == 200, f"HTTP {c2}")
    c, r = appel("GET", "/api/v1/auth/me", "jeton-invalide")
    noter("jeton invalide -> 401 JSON (declencheur du renouvellement cote frontend)", c == 401 and isinstance(r, dict) and "detail" in r, f"HTTP {c}")

    # --- referentiels ---
    c, types = appel("GET", "/api/v1/types-conge/")
    verifier("types-conge (sans authentification)", "GET", "/api/v1/types-conge/", c, types)
    c, r = appel("GET", "/api/v1/jours-feries/")
    verifier("jours-feries", "GET", "/api/v1/jours-feries/", c, r)

    # --- administration (DRH) ---
    for email, nom, service, role in [
        ("cg@demo.tld", "Controleur Gestion", "Finance", "controleur_de_gestion"),
        ("jur@demo.tld", "Service Juridique", "Juridique", "service_juridique"),
        ("df@demo.tld", "Direction Financiere", "Finance", "direction_financiere"),
        ("dg@demo.tld", "Direction Generale", "Direction", "direction_generale"),
    ]:
        c, r = appel("POST", "/api/v1/utilisateurs/", T_DRH, {"email": email, "nom_complet": nom, "service": service, "role": role})
        verifier(f"creer compte {role}", "POST", "/api/v1/utilisateurs/", c, r)
    c, r = appel("GET", "/api/v1/utilisateurs/", T_DRH)
    verifier("lister comptes", "GET", "/api/v1/utilisateurs/", c, r)
    c, r = appel("GET", "/api/v1/utilisateurs/mon-equipe", T_MAN)
    verifier("mon-equipe (manager)", "GET", "/api/v1/utilisateurs/mon-equipe", c, r)
    c, r = appel("PUT", "/api/v1/enveloppes-budgetaires/", T_DRH, {"service": "Support", "exercice": 2026, "budget_alloue": 10000})
    verifier("definir enveloppe", "PUT", "/api/v1/enveloppes-budgetaires/", c, r)
    c, r = appel("GET", "/api/v1/enveloppes-budgetaires/", T_DRH)
    verifier("lister enveloppes", "GET", "/api/v1/enveloppes-budgetaires/", c, r)
    c, r = appel("GET", f"/api/v1/utilisateurs/{moi['id']}/soldes-conges", T_DRH)
    verifier("soldes de conges", "GET", "/api/v1/utilisateurs/{p}/soldes-conges", c, r)

    # --- conges + discussion + decision + fiche ---
    tc = types[0]["id"]
    c, sub = appel("POST", "/api/v1/conges/", T_EMP, {"type_conge_id": tc, "date_debut": "2026-06-01", "date_fin": "2026-06-02"})
    verifier("soumettre conges", "POST", "/api/v1/conges/", c, sub)
    c, r = appel("GET", "/api/v1/conges/", T_EMP)
    verifier("lister mes conges", "GET", "/api/v1/conges/", c, r)
    justif = os.urandom(900)
    corps, ct = multipart({}, "fichier", "certificat.pdf", b"%PDF" + justif)
    c, pj = appel("POST", f"/api/v1/demandes/{sub['id']}/pieces-jointes", T_EMP, brut=corps, entetes={"Content-Type": ct})
    noter("justificatif d'absence (facultatif) depose sur la demande de conges", c == 201 and pj.get("categorie") == "justificatif", f"HTTP {c}")
    c, r = appel("GET", "/api/v1/conges/", T_EMP)
    noter("la liste des conges porte le justificatif", c == 200 and any(p["nom"] == "certificat.pdf" for d in r for p in d.get("pieces_jointes", [])))
    c, r = appel("GET", "/api/v1/conges/agenda-equipe", T_MAN)
    verifier("agenda equipe", "GET", "/api/v1/conges/agenda-equipe", c, r)

    man_id = man_id_de(T_MAN)
    jeton = asyncio.run(jeton_decision(sub["premiere_etape_id"], "approuver", man_id))
    c, ap = appel("GET", f"/api/v1/decisions/{jeton}")
    verifier("apercu de decision (public)", "GET", "/api/v1/decisions/{p}", c, ap)
    c, r = appel("POST", f"/api/v1/demandes/{sub['id']}/suspendre", T_MAN, {"message": "Justificatif illisible."})
    verifier("suspendre pour precisions", "POST", "/api/v1/demandes/{p}/suspendre", c, r)
    c, ap2 = appel("GET", f"/api/v1/decisions/{jeton}")
    noter("apercu pendant la suspension : statut complement_demande", c == 200 and ap2.get("statut_demande") == "complement_demande", f"HTTP {c}")
    c, r = appel("POST", f"/api/v1/demandes/{sub['id']}/messages", T_EMP, {"contenu": "Voici une meilleure version."})
    verifier("demandeur repond", "POST", "/api/v1/demandes/{p}/messages", c, r)
    c, r = appel("GET", f"/api/v1/demandes/{sub['id']}/messages", T_MAN)
    verifier("lister messages", "GET", "/api/v1/demandes/{p}/messages", c, r)
    noter("2 messages dans la discussion", c == 200 and len(r) == 2, f"{len(r) if isinstance(r, list) else r}")
    piece = os.urandom(1500)
    corps, type_contenu = multipart({"contenu": "Voici la piece."}, "fichier", "justificatif.pdf", b"%PDF" + piece)
    c, msg = appel("POST", f"/api/v1/demandes/{sub['id']}/messages/avec-fichier", T_EMP, brut=corps, entetes={"Content-Type": type_contenu})
    noter("depot d'une piece dans la discussion (multipart via le proxy)", c == 201 and msg.get("fichier_nom") == "justificatif.pdf", f"HTTP {c}")
    c, r = appel("GET", f"/api/v1/demandes/{sub['id']}/messages", T_MAN)
    avec = [m for m in r if m.get("fichier_nom")] if c == 200 else []
    noter("la liste des messages expose fichier_nom", len(avec) == 1, f"HTTP {c}")
    c, relu = appel("GET", f"/api/v1/demandes/{sub['id']}/messages/{avec[0]['id']}/fichier", T_MAN) if avec else (0, b"")
    noter("piece relue par l'approbateur identique octet par octet", c == 200 and relu == b"%PDF" + piece, f"HTTP {c}")
    corps_exe, type_exe = multipart({"contenu": "x"}, "fichier", "v.exe", b"MZ", "application/x-msdownload")
    c, r = appel("POST", f"/api/v1/demandes/{sub['id']}/messages/avec-fichier", T_EMP, brut=corps_exe, entetes={"Content-Type": type_exe})
    noter("type de fichier interdit refuse (422)", c == 422, f"HTTP {c}")
    c, r = appel("POST", f"/api/v1/demandes/{sub['id']}/reprendre", T_MAN)
    noter("reprendre le workflow", c == 200 and r.get("statut_global") == "en_cours", f"HTTP {c}")
    c, r = appel("POST", f"/api/v1/decisions/{jeton}", T_MAN, {})
    verifier("decider (approuver)", "POST", "/api/v1/decisions/{p}", c, r)

    # --- relance et annulation des conges (jamais verifiees en reel jusqu'ici) ---
    c, conge2 = appel("POST", "/api/v1/conges/", T_EMP, {"type_conge_id": tc, "date_debut": "2026-08-10", "date_fin": "2026-08-11"})
    noter("second conge soumis pour tester relance/annulation", c == 201, f"HTTP {c}")
    c, relance_cg = appel("POST", f"/api/v1/conges/{conge2['id']}/relancer", T_EMP)
    # RESEND_API_KEY est factice dans cet environnement : l'envoi reel echoue toujours, donc on ne
    # verifie pas la valeur de email_envoye, seulement la forme de la reponse (contrat) et le code 200.
    noter("relance manuelle des conges (forme de la reponse)",
          c == 200 and {"id", "email_envoye", "detail"} <= relance_cg.keys() and isinstance(relance_cg["email_envoye"], bool),
          str(relance_cg))
    c, r = appel("POST", f"/api/v1/conges/{conge2['id']}/annuler", T_EMP)
    noter("annulation des conges", c == 200 and r.get("statut_global") == "annulee", str(r))
    c, r = appel("POST", f"/api/v1/conges/{conge2['id']}/relancer", T_EMP)
    noter("relance refusee sur un conge deja annule (409)", c == 409, f"HTTP {c}")
    c, r = appel("POST", "/api/v1/jours-feries/", T_DRH, {"nom": "Noel", "date": "2026-12-25", "recurrent": True})
    verifier("creer jour ferie", "POST", "/api/v1/jours-feries/", c, r)
    c, r = appel("GET", "/api/v1/jours-feries/")
    verifier("lister jours feries (non vide)", "GET", "/api/v1/jours-feries/", c, r)
    c, r = appel("GET", "/api/v1/conges/agenda-equipe", T_MAN)
    verifier("agenda equipe (conge approuve present)", "GET", "/api/v1/conges/agenda-equipe", c, r)
    noter("l'agenda contient bien le conge approuve", c == 200 and len(r) >= 1)
    c, pdf = appel("GET", f"/api/v1/conges/{sub['id']}/fiche-confirmation", T_EMP)
    noter("fiche de confirmation = vrai PDF", c == 200 and isinstance(pdf, bytes) and pdf[:4] == b"%PDF", f"HTTP {c}")

    # --- notes de frais avec derogation ---
    c, nf = appel("POST", "/api/v1/notes-frais/", T_EMP, {"montant": 90000, "categorie": "Materiel", "date_depense": "2026-03-01", "description": "PC", "derogation_motivee": True, "motif_derogation": "Urgent"})
    verifier("note de frais (derogation)", "POST", "/api/v1/notes-frais/", c, nf)
    noter("routee en derogation", c == 201 and nf.get("derogation") is True)
    # CDC 4.3 : le decideur voit le solde budgetaire (enveloppe Support : 10000 EUR, demande : 90000 EUR).
    c, comptes = appel("GET", "/api/v1/utilisateurs/", T_DRH)
    arbitre = next(u for u in comptes if u["role"] == "controleur_de_gestion")
    jeton_nf = asyncio.run(jeton_decision(nf["premiere_etape_id"], "approuver", arbitre["id"]))
    c, ap_nf = appel("GET", f"/api/v1/decisions/{jeton_nf}")
    b = ap_nf.get("budget") or {}
    noter("apercu note de frais : solde budgetaire chiffre expose au decideur (10000 -> -80000)",
          c == 200 and b.get("solde_disponible") == 10000 and b.get("solde_apres_validation") == -80000, str(b))
    recu = os.urandom(1200)
    corps, ct = multipart({}, "fichier", "recu.pdf", b"%PDF" + recu)
    c, piece = appel("POST", f"/api/v1/demandes/{nf['id']}/pieces-jointes", T_EMP, brut=corps, entetes={"Content-Type": ct})
    noter("recu (facultatif) depose sur la note de frais", c == 201 and piece.get("categorie") == "recu", f"HTTP {c}")
    c, r = appel("GET", "/api/v1/notes-frais/", T_EMP)
    noter("la liste des notes de frais porte le recu", c == 200 and any(p["nom"] == "recu.pdf" for n in r for p in n.get("pieces_jointes", [])))
    c, ap_pj = appel("GET", f"/api/v1/decisions/{jeton_nf}")
    noter("l'apercu de decision de l'approbateur liste le recu (consultation depuis la page de decision)",
          c == 200 and [p["nom"] for p in ap_pj.get("pieces_jointes", [])] == ["recu.pdf"])
    c, relu_recu = appel("GET", f"/api/v1/demandes/{nf['id']}/pieces-jointes/{piece['id']}", T_DRH)
    noter("recu relu identique octet par octet", c == 200 and relu_recu == b"%PDF" + recu, f"HTTP {c}")
    c, _ = appel("GET", f"/api/v1/demandes/{nf['id']}/pieces-jointes/{piece['id']}", T_MAN)
    noter("un manager qui n'est PAS l'approbateur de cette note ne peut pas la lire (403)", c == 403, f"HTTP {c}")
    c, _ = appel("POST", f"/api/v1/demandes/{nf['id']}/pieces-jointes", T_MAN, brut=corps, entetes={"Content-Type": ct})
    noter("seul le demandeur depose (403 pour un autre)", c == 403, f"HTTP {c}")
    c, r = appel("GET", "/api/v1/notes-frais/", T_EMP)
    verifier("lister notes de frais", "GET", "/api/v1/notes-frais/", c, r)
    c, r = appel("POST", "/api/v1/notes-frais/", T_EMP, {"montant": 90000, "categorie": "Materiel", "date_depense": "2026-03-01", "description": "PC"})
    noter("budget insuffisant sans motif -> 422 avec message guidant la derogation", c == 422 and "motif de dérogation" in json.dumps(r, ensure_ascii=False), f"HTTP {c}")

    # --- relance et annulation des notes de frais (parite ajoutee le 28/09 : n'existaient que pour les conges) ---
    c, nf2 = appel("POST", "/api/v1/notes-frais/", T_EMP, {"montant": 50, "categorie": "Repas", "date_depense": "2026-03-01", "description": "Dejeuner client"})
    noter("note de frais soumise pour tester relance/annulation", c == 201, f"HTTP {c}")
    c, relance_nf = appel("POST", f"/api/v1/notes-frais/{nf2['id']}/relancer", T_EMP)
    noter("relance manuelle d'une note de frais (forme de la reponse)",
          c == 200 and {"id", "email_envoye", "detail"} <= relance_nf.keys() and isinstance(relance_nf["email_envoye"], bool),
          str(relance_nf))
    c, _ = appel("POST", f"/api/v1/notes-frais/{nf2['id']}/relancer", T_MAN)
    noter("un tiers (le manager, pas le demandeur ni la DRH) ne peut pas relancer (403)", c == 403, f"HTTP {c}")
    c, r = appel("POST", f"/api/v1/notes-frais/{nf2['id']}/annuler", T_EMP)
    noter("annulation d'une note de frais", c == 200 and r.get("statut_global") == "annulee", str(r))
    c, r = appel("POST", f"/api/v1/notes-frais/{nf2['id']}/relancer", T_EMP)
    noter("relance refusee sur une note deja annulee (409)", c == 409, f"HTTP {c}")
    c, r = appel("POST", f"/api/v1/achats/{nf2['id']}/annuler", T_EMP)
    noter("le prefixe /achats/ ne trouve pas une note de frais (404, pas de fuite entre processus)", c == 404, f"HTTP {c}")

    # --- devises et conversion (decision du 28/09 : plusieurs devises avec conversion) --------
    c, _ = appel("PUT", "/api/v1/taux-change/", T_DRH, {"devise": "usd", "taux": 0.92, "date_effet": "2026-01-01"})
    noter("un taux de change est defini (DRH)", c == 200, f"HTTP {c}")
    c, dv = appel("GET", "/api/v1/devises/", T_EMP)
    noter("la devise USD apparait desormais utilisable", c == 200 and "USD" in {d["code"] for d in dv["devises"]}, str(dv))
    c, conv = appel("GET", "/api/v1/devises/convertir?montant=100&devise=USD&date=2026-03-01", T_EMP)
    noter("conversion a la demande (apercu) : 100 USD -> 92 EUR", c == 200 and conv["montant_reference"] == 92.0, str(conv))

    df = next(u for u in comptes if u["role"] == "direction_financiere")
    T_DF = jeton_acces(df["id"])

    c, note_usd = appel("POST", "/api/v1/notes-frais/", T_EMP, {"montant": 800, "devise": "usd", "categorie": "Materiel", "date_depense": "2026-03-01", "description": "Licence"})
    noter("note de frais en USD : conversion figee et exposee (0.92 -> 736 EUR)",
          c == 201 and note_usd.get("devise") == "USD" and note_usd.get("montant_reference") == 736.0, str(note_usd))
    c, liste_nf = appel("GET", "/api/v1/notes-frais/", T_EMP)
    en_usd = next((n for n in liste_nf if n["id"] == note_usd["id"]), {}) if c == 200 else {}
    noter("le taux applique reste lisible dans la liste du demandeur", en_usd.get("donnees", {}).get("taux_applique") == 0.92, str(en_usd))
    c, sans_taux = appel("POST", "/api/v1/notes-frais/", T_EMP, {"montant": 10, "devise": "gbp", "categorie": "x", "date_depense": "2026-03-01", "description": "x"})
    noter("sans taux defini pour la devise, la soumission est refusee (422) avec un message actionnable",
          c == 422 and "GBP" in sans_taux.get("detail", ""), f"HTTP {c}: {sans_taux}")

    # --- synthese des notes de frais transmise a la comptabilite (CDC 3) ----------------------
    # 800 USD converti a 0.92 = 736 EUR > seuil de 500 EUR : DOIT escalader vers la Direction
    # financiere (preuve que le seuil compare le montant CONVERTI, jamais le montant brut).
    jeton_nf_usd_n1 = asyncio.run(jeton_decision(note_usd["premiere_etape_id"], "approuver", man_id))
    c, decision_n1 = appel("POST", f"/api/v1/decisions/{jeton_nf_usd_n1}", T_MAN, {})
    noter("montant converti (736 EUR) > seuil (500 EUR) : escalade vers la Direction financiere",
          c == 200 and decision_n1.get("statut_global") == "en_cours", str(decision_n1))
    etape2 = asyncio.run(etape_id_niveau(note_usd["id"], 2))
    jeton_nf_usd_n2 = asyncio.run(jeton_decision(etape2, "approuver", df["id"]))
    c, decision_n2 = appel("POST", f"/api/v1/decisions/{jeton_nf_usd_n2}", T_DF, {})
    noter("la Direction financiere valide le second niveau : la demande est terminee",
          c == 200 and decision_n2.get("statut_global") == "terminee", str(decision_n2))

    c, synthese = appel("GET", "/api/v1/notes-frais/synthese", T_DF)
    ligne_usd = next((l for l in synthese.get("elements", []) if l["id"] == note_usd["id"]), None) if c == 200 else None
    noter("la synthese comptabilite liste la note validee avec son montant fige (736 EUR)",
          c == 200 and ligne_usd is not None and ligne_usd["montant_reference"] == 736.0, str(ligne_usd))
    noter("la chaine de validation apparait dans l'ordre (Manager puis Direction financiere)",
          ligne_usd is not None and len(ligne_usd["valide_par"]) == 2, str(ligne_usd))
    c, _ = appel("GET", "/api/v1/notes-frais/synthese", T_EMP)
    noter("un employe n'accede pas a la synthese comptabilite (403)", c == 403, f"HTTP {c}")
    c, csv_brut = appel("GET", "/api/v1/notes-frais/synthese.csv", T_DF)
    noter("export CSV de la synthese : contenu non vide, en-tete conforme",
          c == 200 and isinstance(csv_brut, bytes) and csv_brut.decode("utf-8-sig").startswith("Date de validation"), f"HTTP {c}")
    c, _ = appel("GET", f"/api/v1/demandes/{note_usd['id']}/pieces-jointes", T_DF)
    noter("la Direction financiere consulte les pieces d'une note VALIDEE (comptabilite)", c == 200, f"HTTP {c}")
    c, _ = appel("GET", f"/api/v1/demandes/{nf['id']}/pieces-jointes", T_DF)
    noter("mais pas les pieces d'une note pas encore validee (403)", c == 403, f"HTTP {c}")

    # --- achats multipart ---
    contenu = os.urandom(2000)
    champs = {"tiers": "Fournisseur", "objet": "Licences", "budget_engage": "1200", "derogation_motivee": "false"}
    corps, type_contenu = multipart(champs, "fichier_contrat", "c.pdf", b"%PDF" + contenu)
    c, ach = appel("POST", "/api/v1/achats/", T_EMP, brut=corps, entetes={"Content-Type": type_contenu})
    verifier("achat multipart", "POST", "/api/v1/achats/", c, ach)
    c, r = appel("GET", "/api/v1/achats/", T_EMP)
    verifier("lister achats", "GET", "/api/v1/achats/", c, r)
    corps, ct = multipart({}, "fichier", "annexe.pdf", b"%PDF annexe")
    c, comp = appel("POST", f"/api/v1/demandes/{ach['id']}/pieces-jointes", T_EMP, brut=corps, entetes={"Content-Type": ct})
    noter("document complementaire d'achat depose (categorie complement)", c == 201 and comp.get("categorie") == "complement", f"HTTP {c}")
    c, relu = appel("GET", f"/api/v1/achats/{ach['id']}/piece-jointe", T_EMP)
    noter("contrat relu identique octet par octet", c == 200 and relu == b"%PDF" + contenu, f"HTTP {c}")
    c, r = appel("GET", f"/api/v1/achats/{ach['id']}/bon-de-commande", T_EMP)
    noter("bon de commande avant finalisation -> 409", c == 409, f"HTTP {c}")

    # --- relance et annulation des achats (parite ajoutee le 28/09) ; le niveau 2 (Direction --
    # Generale) est Signataire : la relance doit generer un lien "signer", jamais "approuver". ---
    juriste = next(u for u in comptes if u["role"] == "service_juridique")
    T_JUR = jeton_acces(juriste["id"])
    c, relance_ach1 = appel("POST", f"/api/v1/achats/{ach['id']}/relancer", T_EMP)
    noter("relance d'un achat au niveau Juridique (Approbateur) : forme de la reponse",
          c == 200 and {"id", "email_envoye", "detail"} <= relance_ach1.keys(), str(relance_ach1))
    etape1_id = asyncio.run(etape_id_niveau(ach["id"], 1))
    jeton1 = asyncio.run(jeton_decision(etape1_id, "approuver", juriste["id"]))
    c, d1 = appel("POST", f"/api/v1/decisions/{jeton1}", T_JUR, {})
    noter("achat approuve au niveau Juridique : escalade vers le Signataire (Direction generale)",
          c == 200 and d1.get("statut_global") == "en_cours", str(d1))
    c, relance_ach2 = appel("POST", f"/api/v1/achats/{ach['id']}/relancer", T_EMP)
    noter("relance d'un achat au niveau Signataire : forme de la reponse toujours conforme",
          c == 200 and {"id", "email_envoye", "detail"} <= relance_ach2.keys(), str(relance_ach2))
    c, r = appel("POST", f"/api/v1/achats/{ach['id']}/annuler", T_EMP)
    noter("un achat encore en cours (au niveau Signataire) reste annulable", c == 200 and r.get("statut_global") == "annulee", str(r))
    c, r = appel("POST", f"/api/v1/achats/{ach['id']}/relancer", T_EMP)
    noter("relance refusee sur un achat annule (409)", c == 409, f"HTTP {c}")

    # --- TVA par ligne du bon de commande (decision du 28/09 : detail par ligne, CDC technique 4.1) ---
    dg = next(u for u in comptes if u["role"] == "direction_generale")
    T_DG = jeton_acces(dg["id"])
    lignes_ach = [
        {"description": "Ordinateurs portables", "montant_ht": 1000.0, "taux_tva": 20.0},
        {"description": "Documentation technique", "montant_ht": 50.0, "taux_tva": 5.5},
    ]
    champs_lignes = {"tiers": "Fournisseur Detail", "objet": "Materiel + documentation", "lignes": json.dumps(lignes_ach)}
    corps, ct = multipart(champs_lignes, "fichier_contrat", "c2.pdf", b"%PDF" + os.urandom(500))
    c, ach2 = appel("POST", "/api/v1/achats/", T_EMP, brut=corps, entetes={"Content-Type": ct})
    noter("achat detaille par lignes : budget engage deduit du total TTC (1200 + 52.75)",
          c == 201 and ach2.get("budget_engage_reference") == 1252.75, str(ach2))
    c, liste_ach = appel("GET", "/api/v1/achats/", T_EMP)
    ach2_relu = next((a for a in liste_ach if a["id"] == ach2["id"]), {}) if c == 200 else {}
    noter("les lignes sont conservees telles quelles dans la demande", ach2_relu.get("donnees", {}).get("lignes") == lignes_ach, str(ach2_relu))

    etape1_ach2 = asyncio.run(etape_id_niveau(ach2["id"], 1))
    jeton1_ach2 = asyncio.run(jeton_decision(etape1_ach2, "approuver", juriste["id"]))
    c, _ = appel("POST", f"/api/v1/decisions/{jeton1_ach2}", T_JUR, {})
    noter("achat detaille par lignes approuve au niveau Juridique", c == 200, f"HTTP {c}")
    etape2_ach2 = asyncio.run(etape_id_niveau(ach2["id"], 2))
    jeton2_ach2 = asyncio.run(jeton_decision(etape2_ach2, "signer", dg["id"]))
    c, final_ach2 = appel("POST", f"/api/v1/decisions/{jeton2_ach2}", T_DG, {"signature_image_base64": "iVBORw0KGgo="})
    noter("achat detaille par lignes signe par la Direction generale : termine", c == 200 and final_ach2.get("statut_global") == "terminee", str(final_ach2))
    c, pdf_ach2 = appel("GET", f"/api/v1/achats/{ach2['id']}/bon-de-commande", T_EMP)
    noter("bon de commande genere : PDF reel et de taille substantielle (detail des lignes inclus)",
          c == 200 and isinstance(pdf_ach2, bytes) and pdf_ach2.startswith(b"%PDF") and len(pdf_ach2) > 1000,
          f"HTTP {c}, {len(pdf_ach2) if c == 200 and isinstance(pdf_ach2, bytes) else pdf_ach2}")

    # --- journal d'audit (CDC 2.4) : consultation, controle d'acces, historique du dossier ---
    c, journal = appel("GET", "/api/v1/audit/?limit=200", T_DRH)
    verifier("journal d'audit consultable par la DRH", "GET", "/api/v1/audit/", c, journal)
    actions = {e["action"] for e in journal["elements"]} if c == 200 else set()
    attendues = {"compte_cree", "enveloppe_budgetaire_definie", "jour_ferie_cree", "demande_soumise", "etape_approuvee",
                 "demande_suspendue_precisions", "message_clarification_envoye", "demande_reprise_apres_precisions",
                 "piece_jointe_ajoutee"}
    noter("le journal contient les actions attendues (circuit, discussion, pieces, administration)",
          attendues <= actions, f"manquantes : {sorted(attendues - actions)}")
    c, _ = appel("GET", "/api/v1/audit/", T_EMP)
    noter("un employe ne peut pas consulter le journal (403)", c == 403, f"HTTP {c}")
    c, hist = appel("GET", f"/api/v1/demandes/{sub['id']}/historique", T_EMP)
    libelles = [h["libelle"] for h in hist] if c == 200 else []
    noter("historique du dossier de conges : soumission d'abord, decision en dernier",
          c == 200 and libelles[:1] == ["Demande soumise"] and libelles[-1:] == ["Étape approuvée"], str(libelles))
    noter("l'historique ne reprend pas le contenu des messages de discussion",
          "meilleure version" not in json.dumps(hist, ensure_ascii=False))
    c, _ = appel("GET", f"/api/v1/demandes/{sub['id']}/historique", T_MAN)
    noter("l'approbateur du dossier consulte aussi l'historique", c == 200, f"HTTP {c}")

    print(f"\n{sum(RESULTATS)}/{len(RESULTATS)} verifications reussies")
    sys.exit(0 if all(RESULTATS) else 1)

def man_id_de(token):
    c, m = appel("GET", "/api/v1/auth/me", token)
    return m["id"]

if __name__ == "__main__":
    main()
