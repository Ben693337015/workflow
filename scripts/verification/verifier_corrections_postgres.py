"""
Verification de bout en bout des corrections R9, R17, R18, R19, R21, R22 sur un VRAI PostgreSQL,
avec le role applicatif RESTREINT (celui de la production), a travers les vraies routes HTTP.

Prerequis : base migree (`alembic upgrade head`) et roles crees (`scripts/roles_postgresql.sql`).
    DATABASE_URL=postgresql+asyncpg://workflows_app:<mdp>@host/base \
    python3 scripts/verification/verifier_corrections_postgres.py

Ecrit des donnees de test (comptes verif-*@example.com) : a lancer sur une base jetable.
"""
import asyncio
import os
import re
import sys
import uuid
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("SECRET_KEY", "verif-secret-key-assez-longue-pour-le-test-123456")
os.environ.setdefault("JWT_SECRET_KEY", "verif-jwt-secret-assez-long-pour-le-test-1234567")
os.environ.setdefault("RESEND_API_KEY", "re_verif")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import RoleUtilisateur  # noqa: E402
from app.models.mouvement_conges import MouvementConges  # noqa: E402
from app.models.solde_conges import SoldeConges  # noqa: E402
from app.models.user import Utilisateur  # noqa: E402

MDP = "MotDePasseVerif123!"
ECHECS: list[str] = []
SUFFIXE = uuid.uuid4().hex[:6]


def verifier(condition: bool, libelle: str) -> None:
    print(f"  {'OK ' if condition else 'ECHEC'} {libelle}")
    if not condition:
        ECHECS.append(libelle)


async def _creer(role, prefixe, manager_id=None):
    async with AsyncSessionLocal() as s:
        u = Utilisateur(
            email=f"verif-{prefixe}-{SUFFIXE}@example.com", mot_de_passe_hash=hash_password(MDP),
            nom_complet=prefixe, service="Verif", role=role, manager_id=manager_id,
        )
        s.add(u)
        await s.commit()
        return u.id, u.email


async def _jeton(client, email):
    r = await client.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": MDP})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def main() -> int:
    emails = AsyncMock()
    import app.routers.conges as conges_router

    conges_router.email_service.envoyer_email = emails
    import app.routers.decisions as decisions_router

    decisions_router.email_service.envoyer_email = emails

    manager_id, manager_email = await _creer(RoleUtilisateur.MANAGER, "manager")
    employe_id, employe_email = await _creer(RoleUtilisateur.EMPLOYE, "employe", manager_id)
    _autre_id, autre_email = await _creer(RoleUtilisateur.EMPLOYE, "curieux")
    drh_id, drh_email = await _creer(RoleUtilisateur.DRH, "drh")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        h_drh = await _jeton(client, drh_email)
        h_emp = await _jeton(client, employe_email)
        h_mgr = await _jeton(client, manager_email)
        h_autre = await _jeton(client, autre_email)

        print("\n[Preparation] type de conge, solde de 5 jours (route DRH)")
        type_conge = (await client.post("/api/v1/types-conge/", json={
            "code": f"CP{SUFFIXE}", "nom": "Conge verif", "taux_acquisition_jours_mois": 2.5}, headers=h_drh)).json()
        exercice = 2026
        r = await client.put(f"/api/v1/utilisateurs/{employe_id}/soldes-conges", headers=h_drh,
                             json={"type_conge_id": type_conge["id"], "exercice": exercice, "jours_acquis": 5})
        verifier(r.status_code == 200, "la DRH definit un solde de 5 jours")
        r = await client.put(f"/api/v1/utilisateurs/{employe_id}/soldes-conges", headers=h_drh,
                             json={"type_conge_id": type_conge["id"], "exercice": exercice, "jours_acquis": 5.5})
        verifier(r.status_code == 422, "R4 : un solde en demi-journee est refuse")

        corps = {"type_conge_id": type_conge["id"], "date_debut": "2026-06-01", "date_fin": "2026-06-03"}

        print("\n[R17] 8 soumissions SIMULTANEES de 3 jours pour 5 jours de solde (vraies connexions)")
        reponses = await asyncio.gather(*[client.post("/api/v1/conges/", json=corps, headers=h_emp) for _ in range(8)])
        codes = sorted(x.status_code for x in reponses)
        verifier(codes.count(201) == 1 and codes.count(422) == 7, f"exactement 1 acceptee, 7 refusees ({codes})")
        async with AsyncSessionLocal() as s:
            solde = (await s.execute(select(SoldeConges).where(SoldeConges.utilisateur_id == employe_id))).scalar_one()
            somme = (await s.execute(select(func.sum(MouvementConges.delta)).where(
                MouvementConges.utilisateur_id == employe_id))).scalar_one()
        verifier(float(solde.solde_jours) == 2 and float(solde.jours_reserves) == 3,
                 f"solde disponible 2, reserve 3 (obtenu {solde.solde_jours} / {solde.jours_reserves})")
        verifier(float(somme) == float(solde.solde_jours), "le journal des mouvements explique exactement le solde")
        demande_id = next(x.json()["id"] for x in reponses if x.status_code == 201)
        etape_id = next(x.json()["premiere_etape_id"] for x in reponses if x.status_code == 201)

        print("\n[R19] consultation d'une demande par identifiant")
        verifier((await client.get(f"/api/v1/conges/{demande_id}")).status_code == 401, "sans authentification : 401")
        verifier((await client.get(f"/api/v1/conges/{demande_id}", headers=h_autre)).status_code == 404, "tiers sans lien : 404")
        verifier((await client.get(f"/api/v1/conges/{demande_id}", headers=h_mgr)).status_code == 200, "le manager : 200")
        verifier((await client.get(f"/api/v1/conges/{demande_id}", headers=h_emp)).status_code == 200, "le demandeur : 200")

        print("\n[R17/R18] approbation par le manager via le lien e-mail")
        corps_email = emails.await_args_list[-1].kwargs["corps_html"]
        jeton = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", corps_email).group(1)
        d = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=h_mgr)
        verifier(d.status_code == 200, "decision enregistree")
        async with AsyncSessionLocal() as s:
            solde = (await s.execute(select(SoldeConges).where(SoldeConges.utilisateur_id == employe_id))).scalar_one()
        verifier(float(solde.solde_jours) == 2 and float(solde.jours_pris) == 3 and float(solde.jours_reserves) == 0,
                 f"reservation confirmee sans double debit (dispo {solde.solde_jours}, pris {solde.jours_pris})")

        print("\n[Securite base] le role applicatif ne peut pas falsifier les journaux")
        for table in ("journal_audit", "mouvements_conges"):
            for requete in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}", f"TRUNCATE {table}"):
                async with AsyncSessionLocal() as s:
                    try:
                        await s.execute(text(requete))
                        await s.commit()
                        verifier(False, f"{requete} aurait du etre refuse")
                    except DBAPIError:
                        verifier(True, f"{requete} refuse")

        print("\n[R9] limitation des connexions echouees")
        max_essais = get_settings().connexion_max_tentatives
        for _ in range(max_essais):
            r = await client.post("/api/v1/auth/login", json={"email": autre_email, "mot_de_passe": "mauvais"})
        verifier(r.status_code == 401, f"{max_essais} echecs : 401 sans revelation")
        r = await client.post("/api/v1/auth/login", json={"email": autre_email, "mot_de_passe": MDP})
        verifier(r.status_code == 429 and "Retry-After" in r.headers, "compte verrouille : le BON mot de passe est refuse (429)")

    print("\n" + ("TOUTES LES VERIFICATIONS SONT PASSEES" if not ECHECS else f"{len(ECHECS)} ECHEC(S) : {ECHECS}"))
    return 1 if ECHECS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
