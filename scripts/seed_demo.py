"""
Jeu de donnees de DEMONSTRATION pour le developpement local.

Cree (sans rien dupliquer si on le relance) un compte par role du circuit, un type de conge avec un solde pour
l'employe, et une enveloppe budgetaire pour son service. Tous les circuits sont ainsi testables tout de suite :
conges, notes de frais (y compris > 500 EUR et derogation) et achats (Service juridique puis Direction generale).

Les mots de passe sont connus et publics : ce script REFUSE de s'executer si ENVIRONMENT=production. Pour un
vrai deploiement, creer le premier compte avec scripts/bootstrap_premier_drh.py.

Usage (depuis la racine du projet, ou dans le conteneur) :
    python3 scripts/seed_demo.py
    docker compose exec api python3 scripts/seed_demo.py
"""
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleUtilisateur
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur

# (e-mail, mot de passe, nom, service, role)
COMPTES = [
    ("manager@demo.tld", "ManagerPass123!", "Awa Ndiaye", "Support", RoleUtilisateur.MANAGER),
    ("drh@demo.tld", "DrhPass123!", "Fatou Cissé", "RH", RoleUtilisateur.DRH),
    ("juridique@demo.tld", "JuridiquePass123!", "Moussa Diallo", "Juridique", RoleUtilisateur.SERVICE_JURIDIQUE),
    ("dg@demo.tld", "DgPass123!", "Aminata Sow", "Direction", RoleUtilisateur.DIRECTION_GENERALE),
    ("finance@demo.tld", "FinancePass123!", "Ibrahima Ba", "Finance", RoleUtilisateur.DIRECTION_FINANCIERE),
    ("controle@demo.tld", "ControlePass123!", "Mariam Keita", "Finance", RoleUtilisateur.CONTROLEUR_DE_GESTION),
]
EMPLOYE = ("employe@demo.tld", "EmployePass123!", "Karim Fofana", "Support", RoleUtilisateur.EMPLOYE)


async def _compte(db, email, mot_de_passe, nom, service, role, manager_id=None):
    existant = (await db.execute(select(Utilisateur).where(Utilisateur.email == email))).scalar_one_or_none()
    if existant is not None:
        return existant, False
    u = Utilisateur(
        email=email, mot_de_passe_hash=hash_password(mot_de_passe), nom_complet=nom, service=service,
        role=role, manager_id=manager_id,
    )
    db.add(u)
    await db.flush()
    return u, True


async def seed():
    if get_settings().environment.lower() == "production":
        sys.exit("Refus : ENVIRONMENT=production. Ce script pose des mots de passe publics ; "
                 "utilisez scripts/bootstrap_premier_drh.py.")
    exercice = datetime.now(UTC).year
    crees = []
    async with AsyncSessionLocal() as db:
        manager = None
        for email, mdp, nom, service, role in COMPTES:
            u, neuf = await _compte(db, email, mdp, nom, service, role)
            if email == "manager@demo.tld":
                manager = u
            if neuf:
                crees.append(email)
        employe, neuf = await _compte(db, *EMPLOYE, manager_id=manager.id)
        if neuf:
            crees.append(employe.email)

        type_conge = (await db.execute(select(TypeConge).where(TypeConge.code == "conge_paye"))).scalar_one_or_none()
        if type_conge is None:
            type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
            db.add(type_conge)
            await db.flush()

        solde = (await db.execute(select(SoldeConges).where(
            SoldeConges.utilisateur_id == employe.id, SoldeConges.type_conge_id == type_conge.id,
            SoldeConges.exercice == exercice))).scalar_one_or_none()
        if solde is None:
            db.add(SoldeConges(utilisateur_id=employe.id, type_conge_id=type_conge.id, solde_jours=15,
                               jours_acquis=15, jours_pris=0, exercice=exercice))

        # Sans enveloppe, tout montant depasse « 0 disponible » et part en derogation : on en donne une au service.
        enveloppe = (await db.execute(select(EnveloppeBudgetaire).where(
            EnveloppeBudgetaire.service == "Support", EnveloppeBudgetaire.exercice == exercice))).scalar_one_or_none()
        if enveloppe is None:
            db.add(EnveloppeBudgetaire(service="Support", exercice=exercice, budget_alloue=10000))
        await db.commit()

    print(f"Comptes de démonstration ({len(crees)} créé(s), les autres existaient déjà) :")
    for email, mdp, nom, _s, role in [*COMPTES, EMPLOYE]:
        print(f"  {role.value:<22} {email:<22} {mdp}")
    print(f"Solde : 15 jours de congé payé pour l'employé ({exercice}) ; budget : 10 000 EUR pour le service Support.")


if __name__ == "__main__":
    asyncio.run(seed())
