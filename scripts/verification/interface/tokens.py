import os
OUT = os.environ.get('UI_SORTIE', '/tmp')
import asyncio, uuid, httpx
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import Utilisateur
from app.services import decision_tokens
B="http://localhost:8000"; PWD="MotDePasseVerif123!"; SUF=os.environ["UI_SUFFIXE"]
etA, etC, etB, idB = open(OUT+"/ids.txt").read().split()
async def main():
    async with AsyncSessionLocal() as s:
        mgr=(await s.execute(select(Utilisateur).where(Utilisateur.email==f"verif-manager-{SUF}@example.com"))).scalar_one()
        res={}
        for nom,et,act in (("A",etA,"approuver"),("C",etC,"approuver"),("B",etB,"approuver")):
            res[nom]=await decision_tokens.generer_jeton_decision(s, uuid.UUID(et), act, mgr.id)
        await s.commit()
    with httpx.Client() as c:
        h={"Authorization":"Bearer "+c.post(f"{B}/api/v1/auth/login",json={"email":f"verif-manager-{SUF}@example.com","mot_de_passe":PWD}).json()["access_token"]}
        for nom in ("A","C"):
            r=c.post(f"{B}/api/v1/decisions/{res[nom]}",headers=h,json={}); print("approbation",nom,r.status_code, r.text[:80] if r.status_code!=200 else "")
    open(OUT+"/jeton_B.txt","w").write(res["B"]); print("jeton B prêt")
asyncio.run(main())
