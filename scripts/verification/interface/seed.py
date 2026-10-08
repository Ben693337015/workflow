import os
"""Donnees de test pour verifier l'interface, y compris des textes volontairement extremes."""
import json, sys, httpx
B = "http://localhost:8000"
PWD = "MotDePasseVerif123!"
SUF = os.environ["UI_SUFFIXE"]
emp, mgr, drh = (f"verif-{r}-{SUF}@example.com" for r in ("employe", "manager", "drh"))

def tok(c, email):
    r = c.post(f"{B}/api/v1/auth/login", json={"email": email, "mot_de_passe": PWD}); r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

LONG_MOT = "Supercalifragilisticexpialidocious" * 4          # 136 caracteres SANS espace
LONG_PHRASE = ("Remboursement du deplacement professionnel aller-retour vers le client situe a l'autre bout du pays, "
               "incluant le train, deux nuits d'hotel, les repas et le taxi, avec tous les justificatifs joints. ") * 2
NOM_FICHIER = "justificatif_deplacement_client_tres_important_version_finale_corrigee_signee_2026_octobre_vraiment_tres_long.pdf"

with httpx.Client(timeout=30) as c:
    h_drh, h_emp, h_mgr = tok(c, drh), tok(c, emp), tok(c, mgr)
    c.put(f"{B}/api/v1/enveloppes-budgetaires/", headers=h_drh, json={"service": "Verif", "exercice": 2026, "budget_alloue": 50000}).raise_for_status()
    tc = c.get(f"{B}/api/v1/types-conge/").json()
    tid = tc[0]["id"] if tc else c.post(f"{B}/api/v1/types-conge/", headers=h_drh, json={"code": "cpui", "nom": "Conge paye", "taux_acquisition_jours_mois": 2.5}).json()["id"]
    me = c.get(f"{B}/api/v1/auth/me", headers=h_emp).json()
    c.put(f"{B}/api/v1/utilisateurs/{me['id']}/soldes-conges", headers=h_drh, json={"type_conge_id": tid, "exercice": 2026, "jours_acquis": 25}).raise_for_status()

    # conges
    for d1, d2, com in (("2026-11-02", "2026-11-04", "RAS"), ("2026-12-21", "2026-12-24", LONG_PHRASE), ("2027-01-04", "2027-01-05", LONG_MOT)):
        r = c.post(f"{B}/api/v1/conges/", headers=h_emp, json={"type_conge_id": tid, "date_debut": d1, "date_fin": d2, "commentaire": com})
        print("conge", r.status_code)
    # notes de frais (avec recu au nom tres long)
    for montant, cat, desc in ((499.0, "Voyage", "Train Paris-Lyon"), (80.5, "Restauration", LONG_PHRASE[:480]), (1200, "Hebergement et deplacement longue duree " + "x" * 40, LONG_MOT)):
        r = c.post(f"{B}/api/v1/notes-frais/", headers=h_emp, json={"montant": montant, "categorie": cat[:120], "date_depense": "2026-10-01", "description": desc[:500], "devise": "EUR"})
        print("note", r.status_code, r.text[:90] if r.status_code != 201 else "")
        if r.status_code == 201:
            did = r.json()["id"]
            u = c.post(f"{B}/api/v1/demandes/{did}/pieces-jointes", headers=h_emp, files={"fichier": (NOM_FICHIER, b"%PDF-1.4 test", "application/pdf")})
            print("  recu", u.status_code)
    # achats
    for tiers, objet in (("ACME", "Licences logicielles"), (LONG_MOT[:150] + " Fournisseur International SARL", LONG_PHRASE[:480])):
        r = c.post(f"{B}/api/v1/achats/", headers=h_emp, data={"tiers": tiers[:200], "objet": objet[:500], "budget_engage": "1500"},
                   files={"fichier_contrat": (NOM_FICHIER, b"%PDF-1.4 contrat", "application/pdf")})
        print("achat", r.status_code, r.text[:90] if r.status_code != 201 else "")
