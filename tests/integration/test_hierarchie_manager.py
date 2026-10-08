"""
La DRH change le manager d'un employe ou en attribue un a un compte qui n'en a pas (05/10).
Logique : app/services/hierarchie.py ; route : PATCH /api/v1/utilisateurs/{id}.
"""
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.models.demande import Demande
from app.models.enums import RoleUtilisateur, StatutDemande
from app.models.etape_workflow import EtapeWorkflow
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur
from app.services import decision_tokens
from datetime import UTC, datetime


async def _u(db, role, nom=None, manager_id=None, actif=True):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=nom or f"Test {role.value}", service="Ventes", role=role,
                    manager_id=manager_id, actif=actif)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.fixture
def emails(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.services.email_service.envoyer_email", mock)
    return mock


async def _note(client, db, employe, montant=100.0):
    db.add(EnveloppeBudgetaire(service="Ventes", exercice=datetime.now(UTC).year, budget_alloue=100000))
    await db.commit()
    r = await client.post("/api/v1/notes-frais/", json={
        "montant": montant, "categorie": "Repas", "date_depense": "2026-03-01", "description": "x"}, headers=_h(employe))
    assert r.status_code == 201, r.text
    return r.json()


async def _patch(client, drh, cible, manager_id):
    return await client.patch(f"/api/v1/utilisateurs/{cible.id}", json={"manager_id": manager_id}, headers=_h(drh))


async def test_la_drh_attribue_un_manager_a_un_compte_qui_n_en_a_pas(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)

    r = await _patch(client, drh, employe, str(manager.id))

    assert r.status_code == 200
    assert r.json()["manager_id"] == str(manager.id) and r.json()["demandes_reaffectees"] == 0
    await db_session.refresh(employe)
    assert employe.manager_id == manager.id


async def test_un_employe_sans_manager_peut_ensuite_soumettre(client, db_session, emails):
    """Avant : « Aucun manager rattaché » (422). Apres l'attribution : la note part chez le nouveau manager."""
    drh = await _u(db_session, RoleUtilisateur.DRH)
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=datetime.now(UTC).year, budget_alloue=100000))
    await db_session.commit()
    corps = {"montant": 50.0, "categorie": "Repas", "date_depense": "2026-03-01", "description": "x"}
    avant = await client.post("/api/v1/notes-frais/", json=corps, headers=_h(employe))
    assert avant.status_code == 422

    await _patch(client, drh, employe, str(manager.id))
    apres = await client.post("/api/v1/notes-frais/", json=corps, headers=_h(employe))

    assert apres.status_code == 201
    assert emails.await_args_list[-1].kwargs["destinataire"] == manager.email


async def test_la_drh_change_le_manager_et_l_audit_garde_avant_apres(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    ancien = await _u(db_session, RoleUtilisateur.MANAGER)
    nouveau = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=ancien.id)

    r = await _patch(client, drh, employe, str(nouveau.id))

    assert r.status_code == 200 and r.json()["manager_id"] == str(nouveau.id)
    ligne = (await db_session.execute(select(JournalAudit).where(
        JournalAudit.action == "compte_modifie", JournalAudit.cible_id == employe.id))).scalars().one()
    assert ligne.details["changements"]["manager_id"] == {"avant": str(ancien.id), "apres": str(nouveau.id)}


async def test_seule_la_drh_peut_changer_un_manager(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)

    r = await _patch(client, manager, employe, str(manager.id))

    assert r.status_code == 403


@pytest.mark.parametrize("cas,detail", [
    ("inactif", "désactivé"),
    ("employe", "Employé"),
    ("inconnu", "introuvable"),
])
async def test_manager_invalide_refuse(client, db_session, emails, cas, detail):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    if cas == "inactif":
        cible = str((await _u(db_session, RoleUtilisateur.MANAGER, actif=False)).id)
    elif cas == "employe":
        cible = str((await _u(db_session, RoleUtilisateur.EMPLOYE)).id)
    else:
        cible = str(uuid.uuid4())

    r = await _patch(client, drh, employe, cible)

    assert r.status_code == 422 and detail in r.json()["detail"]
    await db_session.refresh(employe)
    assert employe.manager_id is None


async def test_boucle_hierarchique_refusee(client, db_session, emails):
    """A est le manager de B, B celui de C : rattacher A a C ferait une boucle A -> C -> B -> A."""
    drh = await _u(db_session, RoleUtilisateur.DRH)
    a = await _u(db_session, RoleUtilisateur.MANAGER)
    b = await _u(db_session, RoleUtilisateur.MANAGER, manager_id=a.id)
    c = await _u(db_session, RoleUtilisateur.MANAGER, manager_id=b.id)

    r = await _patch(client, drh, a, str(c.id))

    assert r.status_code == 422 and "boucle" in r.json()["detail"]
    r2 = await _patch(client, drh, a, str(a.id))
    assert r2.status_code == 422


async def test_creation_de_compte_avec_manager_valide_et_invalide(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    inactif = await _u(db_session, RoleUtilisateur.MANAGER, actif=False)
    base = {"nom_complet": "N", "service": "Ventes", "role": "employe"}

    ok = await client.post("/api/v1/utilisateurs/", headers=_h(drh),
                           json={**base, "email": "ok@e.com", "manager_id": str(manager.id)})
    ko = await client.post("/api/v1/utilisateurs/", headers=_h(drh),
                           json={**base, "email": "ko@e.com", "manager_id": str(inactif.id)})

    assert ok.status_code == 201 and ok.json()["manager_id"] == str(manager.id)
    assert ko.status_code == 422


async def test_une_demande_en_cours_est_transmise_au_nouveau_manager(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    ancien = await _u(db_session, RoleUtilisateur.MANAGER)
    nouveau = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=ancien.id)
    d = await _note(client, db_session, employe)
    etape = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"])))).scalar_one()
    ancien_jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", ancien.id)
    await db_session.commit()
    n_avant = len(emails.await_args_list)

    r = await _patch(client, drh, employe, str(nouveau.id))

    assert r.status_code == 200 and r.json()["demandes_reaffectees"] == 1
    await db_session.refresh(etape)
    assert etape.approbateur_attendu_id == nouveau.id
    # le nouveau manager est prevenu, avec de nouveaux liens
    assert len(emails.await_args_list) == n_avant + 1
    assert emails.await_args_list[-1].kwargs["destinataire"] == nouveau.email
    # l'ancien lien est revoque : l'ancien manager ne peut plus decider
    ancien_essai = await client.post(f"/api/v1/decisions/{ancien_jeton}", json={}, headers=_h(ancien))
    assert ancien_essai.status_code in (400, 401, 403, 404, 409, 410)
    # le nouveau manager decide avec le nouveau lien
    nouveau_jeton = emails.await_args_list[-1].kwargs["corps_html"].split("/decisions/")[1].split("'")[0]
    ok = await client.post(f"/api/v1/decisions/{nouveau_jeton}", json={}, headers=_h(nouveau))
    assert ok.status_code == 200, ok.text
    demande = await db_session.get(Demande, uuid.UUID(d["id"]))
    await db_session.refresh(demande)
    assert demande.statut_global == StatutDemande.TERMINEE


async def test_retirer_le_manager_est_refuse_si_une_demande_l_attend(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    ancien = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=ancien.id)
    await _note(client, db_session, employe)

    r = await _patch(client, drh, employe, None)

    assert r.status_code == 409 and "remplaçant" in r.json()["detail"]
    await db_session.refresh(employe)
    assert employe.manager_id == ancien.id


async def test_retirer_le_manager_sans_demande_en_cours_est_possible(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    ancien = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=ancien.id)

    r = await _patch(client, drh, employe, None)

    assert r.status_code == 200 and r.json()["manager_id"] is None


async def test_modifier_un_autre_champ_ne_touche_pas_au_manager_ni_aux_demandes(client, db_session, emails):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _note(client, db_session, employe)
    n_avant = len(emails.await_args_list)

    r = await client.patch(f"/api/v1/utilisateurs/{employe.id}", json={"service": "Ventes"}, headers=_h(drh))

    assert r.status_code == 200 and r.json()["demandes_reaffectees"] == 0
    assert len(emails.await_args_list) == n_avant
