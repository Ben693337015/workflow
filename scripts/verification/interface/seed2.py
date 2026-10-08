import os
import httpx
B="http://localhost:8000"; PWD="MotDePasseVerif123!"; SUF=os.environ["UI_SUFFIXE"]
def tok(c,e):
    return {"Authorization":"Bearer "+c.post(f"{B}/api/v1/auth/login",json={"email":e,"mot_de_passe":PWD}).json()["access_token"]}
LONG_MOT="Supercalifragilisticexpialidocious"*4
LONG_PHRASE=("Remboursement du deplacement professionnel aller-retour vers le client situe a l'autre bout du pays, incluant le train, deux nuits d'hotel, les repas et le taxi, avec tous les justificatifs joints. ")*2
NOM="justificatif_deplacement_client_tres_important_version_finale_corrigee_signee_2026_octobre_vraiment_tres_long.pdf"
with httpx.Client(timeout=30) as c:
    h_drh=tok(c,f"verif-drh-{SUF}@example.com"); h_emp=tok(c,f"verif-employe-{SUF}@example.com")
    for role,nom in (("service_juridique","Juridique Prenom Nom-Tres-Long-De-Famille"),("direction_generale","Directrice Generale")):
        r=c.post(f"{B}/api/v1/utilisateurs/",headers=h_drh,json={"email":f"{role}-{SUF}@example.com","nom_complet":nom,"service":"Direction","role":role})
        print(role,r.status_code,r.text[:100] if r.status_code>=300 else "")
    for tiers,objet in (("ACME","Licences logicielles"),(LONG_MOT[:150]+" Fournisseur International SARL",LONG_PHRASE[:480])):
        r=c.post(f"{B}/api/v1/achats/",headers=h_emp,data={"tiers":tiers[:200],"objet":objet[:500],"budget_engage":"1500"},files={"fichier_contrat":(NOM,b"%PDF-1.4 contrat","application/pdf")})
        print("achat",r.status_code,r.text[:100] if r.status_code!=201 else "")
    tid=c.get(f"{B}/api/v1/types-conge/").json()[0]["id"]
    r=c.post(f"{B}/api/v1/conges/",headers=h_emp,json={"type_conge_id":tid,"date_debut":"2027-01-04","date_fin":"2027-01-05","commentaire":LONG_MOT[:100]}); print("conge",r.status_code,r.text[:100] if r.status_code!=201 else "")
