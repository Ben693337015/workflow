import os
OUT = os.environ.get('UI_SORTIE', '/tmp')
import asyncio, os, sys, httpx
sys.path.insert(0, "/home/claude/proj/workflow-main")
B="http://localhost:8000"; PWD="MotDePasseVerif123!"; SUF=os.environ["UI_SUFFIXE"]
LONG_MOT="Supercalifragilisticexpialidocious"*5
LONG_PHRASE="Je vous remercie de bien vouloir me preciser le motif exact de ce deplacement ainsi que la liste complete des participants et le budget previsionnel valide par la direction. "*3
def tok(c,e): return {"Authorization":"Bearer "+c.post(f"{B}/api/v1/auth/login",json={"email":e,"mot_de_passe":PWD}).json()["access_token"]}
with httpx.Client(timeout=30) as c:
    h_emp=tok(c,f"verif-employe-{SUF}@example.com"); h_mgr=tok(c,f"verif-manager-{SUF}@example.com")
    tid=c.get(f"{B}/api/v1/types-conge/").json()[0]["id"]
    out={}
    r=c.post(f"{B}/api/v1/conges/",headers=h_emp,json={"type_conge_id":tid,"date_debut":"2027-02-01","date_fin":"2027-02-02","commentaire":"Conge pour demenagement "+LONG_MOT[:60]}); out["A"]=r.json(); print("A",r.status_code)
    r=c.post(f"{B}/api/v1/conges/",headers=h_emp,json={"type_conge_id":tid,"date_debut":"2027-03-01","date_fin":"2027-03-02","commentaire":"Voyage"}); out["B"]=r.json(); print("B",r.status_code)
    r=c.post(f"{B}/api/v1/notes-frais/",headers=h_emp,json={"montant":120,"categorie":"Restauration","date_depense":"2026-10-02","description":"Repas client "+LONG_MOT,"devise":"EUR"}); out["C"]=r.json(); print("C",r.status_code, r.text[:80] if r.status_code!=201 else "")
    for k in out: print(k, {x:out[k].get(x) for x in ("id","premiere_etape_id")})
    # discussion sur B : le manager suspend, messages longs de part et d'autre
    idB=out["B"]["id"]
    print("suspendre",c.post(f"{B}/api/v1/demandes/{idB}/suspendre",headers=h_mgr,json={"message":LONG_PHRASE}).status_code)
    print("reponse",c.post(f"{B}/api/v1/demandes/{idB}/messages",headers=h_emp,json={"contenu":LONG_MOT+" "+LONG_PHRASE}).status_code)
    print("mgr",c.post(f"{B}/api/v1/demandes/{idB}/messages",headers=h_mgr,json={"contenu":"https://exemple.org/"+LONG_MOT+"/"+LONG_MOT}).status_code)
    open(OUT+"/ids.txt","w").write(f"{out['A']['premiere_etape_id']} {out['C']['premiere_etape_id']} {out['B']['premiere_etape_id']} {idB}")
