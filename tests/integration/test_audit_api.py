"""
Consultation du journal d'audit (CDC fonctionnel 2.4) : qui a fait quoi, et quand - pour les roles
de controle - et historique d'un dossier pour ses participants. Consignation des actions
d'administration.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.security import create_access_token
from app.models.demande import Demande
from app.models.enums import RoleEtape, RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur
from app.services import audit


async def _u(db, role, nom=None):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=nom or f"Test {role.value}", service="Ventes", role=role)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.fixture(autouse=True)
def _pas_d_email(monkeypatch):
    monkeypatch.setattr("app.services.email_service.envoyer_email", AsyncMock())


# --- acces ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [RoleUtilisateur.DRH, RoleUtilisateur.DIRECTION_GENERALE, RoleUtilisateur.CONTROLEUR_DE_GESTION])
async def test_les_roles_de_controle_consultent_le_journal(client, db_session, role):
    u = await _u(db_session, role)
    assert (await client.get("/api/v1/audit/", headers=_h(u))).status_code == 200
    assert (await client.get("/api/v1/audit/actions", headers=_h(u))).status_code == 200


@pytest.mark.parametrize("role", [RoleUtilisateur.EMPLOYE, RoleUtilisateur.MANAGER, RoleUtilisateur.SERVICE_JURIDIQUE, RoleUtilisateur.DIRECTION_FINANCIERE])
async def test_les_autres_roles_ne_consultent_pas_le_journal(client, db_session, role):
    u = await _u(db_session, role)
    assert (await client.get("/api/v1/audit/", headers=_h(u))).status_code == 403


async def test_sans_authentification_401(client):
    assert (await client.get("/api/v1/audit/")).status_code == 401


# --- recherche -----------------------------------------------------------------------

def _inserer(db, action, acteur, cible_type, cible_id, details, quand):
    """INSERT avec un horodatage choisi. On n'antidate jamais apres coup : ce serait modifier le journal."""
    db.add(JournalAudit(action=action, acteur_id=acteur.id if acteur else None, cible_type=cible_type,
                        cible_id=cible_id, details=details, horodate_le=quand))


async def _semer(db, acteur, n=5, action="demande_soumise"):
    for i in range(n):
        _inserer(db, action, acteur, "demande", uuid.uuid4(), {"i": i}, datetime.now(UTC) - timedelta(minutes=n - i))
    await db.commit()


async def test_pagination_ordre_du_plus_recent_et_total(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    await _semer(db_session, drh, n=5)

    page1 = (await client.get("/api/v1/audit/", params={"limit": 2, "offset": 0}, headers=_h(drh))).json()
    page3 = (await client.get("/api/v1/audit/", params={"limit": 2, "offset": 4}, headers=_h(drh))).json()

    assert page1["total"] == 5 and len(page1["elements"]) == 2 and len(page3["elements"]) == 1
    assert [e["details"]["i"] for e in page1["elements"]] == [4, 3]  # le plus recent d'abord
    assert page3["elements"][0]["details"]["i"] == 0


async def test_les_bornes_de_pagination_sont_validees(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        assert (await client.get("/api/v1/audit/", params=params, headers=_h(drh))).status_code == 422


async def test_filtres_action_acteur_cible_et_dates(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    autre = await _u(db_session, RoleUtilisateur.MANAGER)
    await _semer(db_session, drh, n=2, action="demande_soumise")
    await _semer(db_session, autre, n=3, action="etape_approuvee")
    get = lambda **p: client.get("/api/v1/audit/", params=p, headers=_h(drh))

    assert (await get(action="etape_approuvee")).json()["total"] == 3
    assert (await get(acteur_id=str(drh.id))).json()["total"] == 2
    assert (await get(cible_type="demande")).json()["total"] == 5
    assert (await get(cible_type="utilisateur")).json()["total"] == 0
    futur = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    passe = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert (await get(depuis=futur)).json()["total"] == 0
    assert (await get(jusqu_a=passe)).json()["total"] == 0
    assert (await get(depuis=passe, jusqu_a=futur)).json()["total"] == 5


async def test_filtre_par_cible_precise(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    cible = uuid.uuid4()
    await audit.consigner(db_session, action="demande_soumise", acteur_id=drh.id, cible_type="demande", cible_id=cible, details={})
    await audit.consigner(db_session, action="demande_soumise", acteur_id=drh.id, cible_type="demande", cible_id=uuid.uuid4(), details={})
    await db_session.commit()

    reponse = (await client.get("/api/v1/audit/", params={"cible_id": str(cible)}, headers=_h(drh))).json()

    assert reponse["total"] == 1 and reponse["elements"][0]["cible_id"] == str(cible)


async def test_une_action_systeme_sans_acteur_est_attribuee_au_systeme_et_les_libelles_sont_francais(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    await audit.consigner(db_session, action="rappel_automatique", acteur_id=None, cible_type="etape_workflow", cible_id=None, details={})
    await audit.consigner(db_session, action="action_inconnue_future", acteur_id=drh.id, cible_type="x", cible_id=None, details={})
    await db_session.commit()

    elements = {e["action"]: e for e in (await client.get("/api/v1/audit/", headers=_h(drh))).json()["elements"]}

    assert elements["rappel_automatique"]["acteur_nom"] == "Système" and elements["rappel_automatique"]["acteur_id"] is None
    assert elements["rappel_automatique"]["libelle"] == "Rappel automatique"
    assert elements["action_inconnue_future"]["libelle"] == "action_inconnue_future"  # jamais d'erreur sur une action inconnue
    assert elements["action_inconnue_future"]["acteur_nom"] == drh.nom_complet


async def test_le_filtre_d_actions_couvre_toutes_les_actions_consignees_par_le_code(client, db_session):
    """Aucune action consignee ne doit manquer du libelle (sinon l'ecran afficherait un identifiant technique)."""
    import re
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2] / "app"
    trouvees = set()
    for fichier in racine.rglob("*.py"):
        for m in re.finditer(r'action="([a-z_]+)"', fichier.read_text(encoding="utf-8")):
            trouvees.add(m.group(1))
    trouvees |= {"etape_approuvee", "etape_signee", "etape_refusee"}  # actions calculees dans decisions.py

    manquantes = sorted(a for a in trouvees if a not in audit.LIBELLES)
    assert manquantes == []


# --- actions d'administration consignees -----------------------------------------------

async def test_les_actions_d_administration_sont_consignees_avec_avant_et_apres(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    h = _h(drh)

    await client.put("/api/v1/enveloppes-budgetaires/", json={"service": "Ventes", "exercice": 2026, "budget_alloue": 1000}, headers=h)
    await client.put("/api/v1/enveloppes-budgetaires/", json={"service": "Ventes", "exercice": 2026, "budget_alloue": 1500}, headers=h)
    cree = (await client.post("/api/v1/utilisateurs/", json={"email": "nouveau@e.com", "nom_complet": "Nouveau", "service": "Ventes", "role": "employe"}, headers=h)).json()
    await client.patch(f"/api/v1/utilisateurs/{cree['id']}", json={"role": "manager", "service": "Finance"}, headers=h)
    await client.post(f"/api/v1/utilisateurs/{cree['id']}/desactiver", headers=h)
    await client.post(f"/api/v1/utilisateurs/{cree['id']}/reactiver", headers=h)
    type_conge = (await client.post("/api/v1/types-conge/", json={"code": "TEST", "nom": "Test", "taux_acquisition_jours_mois": 1.5}, headers=h)).json()
    await client.put(f"/api/v1/utilisateurs/{cree['id']}/soldes-conges", json={"type_conge_id": type_conge["id"], "exercice": 2026, "jours_acquis": 10}, headers=h)
    await client.put(f"/api/v1/utilisateurs/{cree['id']}/soldes-conges", json={"type_conge_id": type_conge["id"], "exercice": 2026, "jours_acquis": 12}, headers=h)
    await client.post(f"/api/v1/types-conge/{type_conge['id']}/desactiver", headers=h)
    await client.post(f"/api/v1/types-conge/{type_conge['id']}/reactiver", headers=h)
    await client.post("/api/v1/jours-feries/", json={"nom": "Noel", "date": "2026-12-25", "recurrent": True}, headers=h)

    journal = (await client.get("/api/v1/audit/", params={"limit": 200}, headers=h)).json()["elements"]
    par_action = {}
    for e in journal:
        par_action.setdefault(e["action"], []).append(e)

    attendues = {"enveloppe_budgetaire_definie": 2, "compte_cree": 1, "compte_modifie": 1, "compte_desactive": 1,
                 "compte_reactive": 1, "type_conge_cree": 1, "solde_conges_defini": 2, "type_conge_desactive": 1,
                 "type_conge_reactive": 1, "jour_ferie_cree": 1}
    assert {a: len(v) for a, v in par_action.items()} == attendues
    assert all(e["acteur_id"] == str(drh.id) and e["acteur_nom"] == drh.nom_complet for e in journal)  # l'auteur est toujours la DRH

    budgets = sorted(par_action["enveloppe_budgetaire_definie"], key=lambda e: e["horodate_le"])
    assert [(b["details"]["budget_alloue_avant"], b["details"]["budget_alloue_apres"]) for b in budgets] == [(None, 1000.0), (1000.0, 1500.0)]
    assert par_action["compte_modifie"][0]["details"]["changements"] == {
        "role": {"avant": "employe", "apres": "manager"}, "service": {"avant": "Ventes", "apres": "Finance"},
    }
    soldes = sorted(par_action["solde_conges_defini"], key=lambda e: e["horodate_le"])
    assert [(s["details"]["jours_acquis_avant"], s["details"]["jours_acquis_apres"]) for s in soldes] == [(None, 10.0), (10.0, 12.0)]


async def test_une_modification_sans_effet_ne_pollue_pas_le_journal(client, db_session):
    drh = await _u(db_session, RoleUtilisateur.DRH)
    cible = await _u(db_session, RoleUtilisateur.EMPLOYE)

    await client.patch(f"/api/v1/utilisateurs/{cible.id}", json={"service": cible.service}, headers=_h(drh))  # meme valeur

    journal = (await client.get("/api/v1/audit/", params={"action": "compte_modifie"}, headers=_h(drh))).json()
    assert journal["total"] == 0


# --- historique d'un dossier -------------------------------------------------------------

async def _dossier(db):
    manager = await _u(db, RoleUtilisateur.MANAGER, "Marie Manager")
    employe = await _u(db, RoleUtilisateur.EMPLOYE, "Eric Employe")
    d = Demande(processus=TypeProcessus.NOTES_FRAIS, demandeur_id=employe.id, initiee_par_id=employe.id,
                donnees={"montant": 50}, statut_global=StatutDemande.EN_COURS)
    db.add(d)
    await db.flush()
    e = EtapeWorkflow(demande_id=d.id, niveau=1, role=RoleEtape.APPROBATEUR, approbateur_attendu_id=manager.id)
    db.add(e)
    await db.commit()
    t0 = datetime.now(UTC) - timedelta(hours=3)
    evenements = [
        ("demande_soumise", employe, "demande", d.id, {"processus": "notes_frais", "motif_derogation": "Urgent"}),
        ("rappel_automatique", None, "etape_workflow", e.id, {"numero_rappel": 1}),
        ("message_clarification_envoye", employe, "demande", d.id, {"message": "SECRET-du-message"}),
        ("piece_jointe_ajoutee", employe, "demande", d.id, {"fichier": "recu.pdf", "categorie": "recu"}),
        ("etape_approuvee", manager, "etape_workflow", e.id, {"commentaire": "OK pour moi", "justification_acceptation": "Cas exceptionnel"}),
    ]
    for i, (action, acteur, cible_type, cible_id, details) in enumerate(evenements):
        _inserer(db, action, acteur, cible_type, cible_id, details, t0 + timedelta(minutes=i))
    # bruit : une entree d'une AUTRE demande, qui ne doit jamais apparaitre
    _inserer(db, "demande_soumise", employe, "demande", uuid.uuid4(), {}, t0)
    await db.commit()
    return d, manager, employe


async def test_l_historique_est_chronologique_lisible_et_limite_au_dossier(client, db_session):
    d, manager, employe = await _dossier(db_session)

    historique = (await client.get(f"/api/v1/demandes/{d.id}/historique", headers=_h(manager))).json()

    assert [h["libelle"] for h in historique] == [
        "Demande soumise", "Rappel automatique", "Message dans la discussion", "Pièce jointe ajoutée", "Étape approuvée",
    ]
    assert [h["acteur_nom"] for h in historique] == ["Eric Employe", "Système", "Eric Employe", "Eric Employe", "Marie Manager"]
    details = [h["detail"] for h in historique]
    assert details[0] == "Dérogation demandée : Urgent"
    assert details[1] == "Rappel n°1" and details[3] == "recu.pdf"
    assert details[4] == "Commentaire : OK pour moi — Justification d'acceptation : Cas exceptionnel"


async def test_l_historique_ne_reprend_pas_le_contenu_des_messages_de_discussion(client, db_session):
    d, manager, _ = await _dossier(db_session)

    corps = (await client.get(f"/api/v1/demandes/{d.id}/historique", headers=_h(manager))).text

    assert "SECRET-du-message" not in corps  # le contenu a sa propre route et ses propres regles d'acces
    assert "Message dans la discussion" in corps  # mais l'evenement, lui, est bien trace


async def test_participants_autorises_et_tiers_exclus(client, db_session):
    d, manager, employe = await _dossier(db_session)
    drh = await _u(db_session, RoleUtilisateur.DRH)
    tiers = await _u(db_session, RoleUtilisateur.MANAGER)

    for qui in (employe, manager, drh):
        assert (await client.get(f"/api/v1/demandes/{d.id}/historique", headers=_h(qui))).status_code == 200
    assert (await client.get(f"/api/v1/demandes/{d.id}/historique", headers=_h(tiers))).status_code == 403
    assert (await client.get(f"/api/v1/demandes/{uuid.uuid4()}/historique", headers=_h(drh))).status_code == 404
    assert (await client.get("/api/v1/demandes/pas-un-uuid/historique", headers=_h(drh))).status_code == 404
