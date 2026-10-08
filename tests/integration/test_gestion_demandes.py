"""
Annulation et relance manuelle pour les notes de frais et les achats (écart corrigé le 28/09 :
ces deux actions n'existaient que pour les congés). Logique partagée : app/services/gestion_demandes.py.
"""
from tests.signature_factory import SIGNATURE_PNG
import re
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleUtilisateur, StatutDemande
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur
from app.services import decision_tokens


async def _u(db, role, service="Ventes", nom=None, manager_id=None):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=nom or f"Test {role.value}", service=service, role=role, manager_id=manager_id)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


async def _budget(db, alloue, service="Ventes", exercice=None):
    db.add(EnveloppeBudgetaire(service=service, exercice=exercice or datetime.now(UTC).year, budget_alloue=alloue))
    await db.commit()


@pytest.fixture
def emails(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.services.email_service.envoyer_email", mock)
    return mock


async def _note_de_frais(client, employe, montant=100.0):
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        r = await client.post("/api/v1/notes-frais/", json={
            "montant": montant, "categorie": "Repas", "date_depense": "2026-03-01", "description": "x",
        })
        return r.json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def _achat(client, employe, budget=100.0):
    # ACHATS route vers le role Service juridique (pas via un manager) : un compte de ce role doit
    # deja exister en base avant cet appel, sinon la soumission echoue (422, aucun approbateur).
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        r = await client.post(
            "/api/v1/achats/",
            data={"tiers": "Fournisseur X", "objet": "Licences", "budget_engage": str(budget)},
            files={"fichier_contrat": ("c.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        return r.json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ============================================================================
# ANNULATION
# ============================================================================

@pytest.mark.parametrize("prefixe, creer", [("notes-frais", _note_de_frais), ("achats", _achat)])
async def test_le_demandeur_annule_sa_demande_en_cours(client, db_session, emails, prefixe, creer):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")  # requis pour router un achat
    await _budget(db_session, 10000)
    d = await creer(client, employe)

    reponse = await client.post(f"/api/v1/{prefixe}/{d['id']}/annuler", headers=_h(employe))

    assert reponse.status_code == 200
    assert reponse.json() == {"id": d["id"], "statut_global": "annulee"}
    trace = (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "demande_annulee"))).scalar_one()
    assert trace.acteur_id == employe.id and trace.cible_id == uuid.UUID(d["id"])


@pytest.mark.parametrize("prefixe, creer", [("notes-frais", _note_de_frais), ("achats", _achat)])
async def test_un_tiers_ne_peut_pas_annuler(client, db_session, emails, prefixe, creer):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    tiers = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")  # requis pour router un achat
    await _budget(db_session, 10000)
    d = await creer(client, employe)

    reponse = await client.post(f"/api/v1/{prefixe}/{d['id']}/annuler", headers=_h(tiers))

    assert reponse.status_code == 403


@pytest.mark.parametrize("prefixe, creer", [("notes-frais", _note_de_frais), ("achats", _achat)])
async def test_une_demande_deja_terminee_ne_se_reannule_pas(client, db_session, emails, prefixe, creer):
    from app.services import decision_tokens as dt

    manager = await _u(db_session, RoleUtilisateur.MANAGER) if prefixe == "notes-frais" else await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id if prefixe == "notes-frais" else None)
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction") if prefixe == "achats" else None
    await _budget(db_session, 10000)
    d = await creer(client, employe, montant=50.0) if prefixe == "notes-frais" else await creer(client, employe, budget=50.0)

    etape1 = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"]), EtapeWorkflow.niveau == 1))).scalar_one()
    jeton1 = await dt.generer_jeton_decision(db_session, etape1.id, "approuver", etape1.approbateur_attendu_id)
    await db_session.commit()
    await client.post(f"/api/v1/decisions/{jeton1}", json={}, headers=_h(manager))
    if prefixe == "achats":
        etape2 = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"]), EtapeWorkflow.niveau == 2))).scalar_one()
        jeton2 = await dt.generer_jeton_decision(db_session, etape2.id, "signer", etape2.approbateur_attendu_id)
        await db_session.commit()
        await client.post(f"/api/v1/decisions/{jeton2}", json={"signature_image_base64": SIGNATURE_PNG}, headers=_h(dg))

    reponse = await client.post(f"/api/v1/{prefixe}/{d['id']}/annuler", headers=_h(employe))

    assert reponse.status_code == 409


async def test_annulation_pendant_une_suspension_pour_precisions_reste_possible(client, db_session, emails):
    """Écart n°5 (communication bidirectionnelle) : le demandeur doit pouvoir se retirer même pendant une discussion."""
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    etape = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"])))).scalar_one()
    await client.post(f"/api/v1/demandes/{d['id']}/suspendre", json={"message": "Précisez le motif."}, headers=_h(manager))

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/annuler", headers=_h(employe))

    assert reponse.status_code == 200 and reponse.json()["statut_global"] == "annulee"


async def test_le_bon_prefixe_de_route_ne_trouve_pas_la_demande_de_l_autre_processus(client, db_session, emails):
    """Une note de frais n'est pas annulable via /api/v1/achats/, et réciproquement (404, pas 200 par erreur)."""
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")  # requis pour router un achat
    await _budget(db_session, 10000)
    note = await _note_de_frais(client, employe)
    achat = await _achat(client, employe)

    assert (await client.post(f"/api/v1/achats/{note['id']}/annuler", headers=_h(employe))).status_code == 404
    assert (await client.post(f"/api/v1/notes-frais/{achat['id']}/annuler", headers=_h(employe))).status_code == 404


# ============================================================================
# RELANCE MANUELLE
# ============================================================================

async def _dernier_jeton(mock, libelle="Approuver"):
    dernier = mock.await_args_list[-1]
    return re.search(rf"/decisions/([A-Za-z0-9_\-\.]+)'>{libelle}", dernier.kwargs["corps_html"]).group(1)


async def test_le_demandeur_relance_une_note_de_frais_en_attente(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    n_avant = len(emails.await_args_list)

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 200 and reponse.json()["email_envoye"] is True
    assert len(emails.await_args_list) == n_avant + 1
    dernier = emails.await_args_list[-1]
    assert dernier.kwargs["destinataire"] == manager.email
    assert "Rappel" in dernier.kwargs["sujet"]
    assert "note de frais" in dernier.kwargs["corps_html"]


async def test_le_solde_budgetaire_figure_dans_l_email_de_relance(client, db_session, emails):
    """CDC 4.3 : le décideur doit voir le solde disponible, y compris lors d'une relance."""
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 1000)
    d = await _note_de_frais(client, employe, montant=300.0)

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 200
    corps = emails.await_args_list[-1].kwargs["corps_html"]
    assert "Solde disponible : 1000.0 €" in corps and "Solde après validation : 700.0 €" in corps


async def test_la_drh_peut_aussi_relancer_une_note_de_frais(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    drh = await _u(db_session, RoleUtilisateur.DRH)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(drh))

    assert reponse.status_code == 200


async def test_un_tiers_quelconque_ne_peut_pas_relancer(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    tiers = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(tiers))

    assert reponse.status_code == 403


async def test_relance_refusee_si_la_demande_n_est_plus_en_cours(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    etape = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"])))).scalar_one()
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    await db_session.commit()
    await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=_h(manager))

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 409


async def test_relance_refusee_pendant_une_suspension_aucune_etape_en_attente(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    await client.post(f"/api/v1/demandes/{d['id']}/suspendre", json={"message": "Précisez."}, headers=_h(manager))

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 409  # statut_global == complement_demande, plus "en_cours"


async def test_relance_revoque_l_ancien_jeton_et_en_emet_un_nouveau(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    ancien_jeton = await _dernier_jeton(emails)

    await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))
    nouveau_jeton = await _dernier_jeton(emails)

    assert nouveau_jeton != ancien_jeton
    assert (await client.post(f"/api/v1/decisions/{ancien_jeton}", json={}, headers=_h(manager))).status_code == 401
    assert (await client.post(f"/api/v1/decisions/{nouveau_jeton}", json={}, headers=_h(manager))).status_code == 200


async def test_un_achat_au_niveau_signataire_est_relance_avec_un_lien_signer_jamais_approuver(client, db_session, emails):
    """Le second niveau d'un achat (Direction Générale) est Signataire, pas Approbateur : la relance
    doit refléter cette différence de rôle, exactement comme le rappel automatique."""
    juriste = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    d = await _achat(client, employe)

    etape1 = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"]), EtapeWorkflow.niveau == 1))).scalar_one()
    jeton1 = await decision_tokens.generer_jeton_decision(db_session, etape1.id, "approuver", juriste.id)
    await db_session.commit()
    await client.post(f"/api/v1/decisions/{jeton1}", json={}, headers=_h(juriste))
    emails.reset_mock()

    reponse = await client.post(f"/api/v1/achats/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 200 and reponse.json()["email_envoye"] is True
    dernier = emails.await_args_list[-1]
    assert dernier.kwargs["destinataire"] == dg.email
    assert "signature requise" in dernier.kwargs["corps_html"]
    lien_signer = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Signer", dernier.kwargs["corps_html"])
    assert lien_signer is not None, dernier.kwargs["corps_html"]
    assert "'>Approuver" not in dernier.kwargs["corps_html"]  # jamais "approuver" pour un signataire

    jeton = lien_signer.group(1)
    assert (await client.post(f"/api/v1/decisions/{jeton}", json={"signature_image_base64": SIGNATURE_PNG}, headers=_h(dg))).status_code == 200


async def test_un_echec_d_envoi_n_empeche_pas_la_revocation_ni_la_reponse(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    emails.side_effect = RuntimeError("Resend indisponible")

    reponse = await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 200
    assert reponse.json()["email_envoye"] is False
    assert "n'a pas pu être envoyé" in reponse.json()["detail"]


async def test_relance_consignee_au_journal(client, db_session, emails):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)

    await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))

    trace = (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "decision_relancee"))).scalar_one()
    assert trace.acteur_id == employe.id and trace.details == {"relance_par": str(employe.id)}


async def test_relance_manuelle_n_interfere_pas_avec_le_cycle_des_rappels_automatiques(client, db_session, emails):
    """La relance manuelle ne touche pas dernier_rappel_le / nombre_rappels : les deux mécanismes
    restent indépendants, sans se voler mutuellement un passage."""
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session, 10000)
    d = await _note_de_frais(client, employe)
    etape = (await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid.UUID(d["id"])))).scalar_one()
    assert (etape.dernier_rappel_le, etape.nombre_rappels) == (None, 0)

    await client.post(f"/api/v1/notes-frais/{d['id']}/relancer", headers=_h(employe))
    await db_session.refresh(etape)

    assert (etape.dernier_rappel_le, etape.nombre_rappels) == (None, 0)


async def test_relance_d_un_achat_reprend_bien_le_prefixe_de_route(client, db_session, emails):
    juriste = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, 10000)
    d = await _achat(client, employe)

    reponse = await client.post(f"/api/v1/achats/{d['id']}/relancer", headers=_h(employe))

    assert reponse.status_code == 200
    assert emails.await_args_list[-1].kwargs["destinataire"] == juriste.email
    assert "demande d'achat" in emails.await_args_list[-1].kwargs["corps_html"]
