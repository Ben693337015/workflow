"""
Test d'intégration - route de décision par lien e-mail (section 9 / 13.3).

Couvre le cas congés (un seul niveau) : approbation -> circuit terminé,
refus -> commentaire obligatoire, jeton réutilisé -> conflit, mauvais
approbateur connecté -> 403, session absente alors qu'elle est exigée -> 401.
"""
from unittest.mock import AsyncMock

import pytest

from app.core.security import create_access_token
from app.models.demande import Demande
from app.models.enums import RoleEtape, RoleUtilisateur, StatutDemande, StatutEtape, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.services import decision_tokens


async def _preparer_demande_en_attente(db_session, solde_jours: float = 10):
    type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.flush()

    manager = Utilisateur(
        email="manager@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Manager Test",
        service="Support",
        role=RoleUtilisateur.MANAGER,
    )
    autre_utilisateur = Utilisateur(
        email="quelquun-dautre@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Quelqu'un d'Autre",
        service="Support",
        role=RoleUtilisateur.MANAGER,
    )
    db_session.add_all([manager, autre_utilisateur])
    await db_session.flush()

    employe = Utilisateur(
        email="employe@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Employe Test",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
        manager_id=manager.id,
    )
    db_session.add(employe)
    await db_session.flush()

    db_session.add(
        SoldeConges(
            utilisateur_id=employe.id,
            type_conge_id=type_conge.id,
            solde_jours=solde_jours,
            jours_acquis=solde_jours,
            jours_pris=0,
            exercice=2026,
        )
    )

    drh = Utilisateur(
        email="drh@example.com",
        mot_de_passe_hash="hash",
        nom_complet="DRH Test",
        service="RH",
        role=RoleUtilisateur.DRH,
    )
    db_session.add(drh)
    await db_session.flush()

    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-03",
        },
        statut_global=StatutDemande.EN_COURS,
    )
    db_session.add(demande)
    await db_session.flush()

    etape = EtapeWorkflow(
        demande_id=demande.id,
        niveau=1,
        role=RoleEtape.APPROBATEUR,
        approbateur_attendu_id=manager.id,
    )
    db_session.add(etape)
    await db_session.commit()
    await db_session.refresh(etape)
    await db_session.refresh(demande)

    return demande, etape, manager, autre_utilisateur, employe, type_conge, drh


@pytest.fixture(autouse=True)
def _mock_effets_de_bord(monkeypatch):
    """Evite tout appel reseau reel (Resend) pendant les tests de decision."""
    mock_email = AsyncMock()
    monkeypatch.setattr("app.routers.decisions.email_service.envoyer_email", mock_email)
    return mock_email


async def test_approbation_par_le_bon_manager_termine_le_circuit(client, db_session):
    demande, etape, manager, _, _employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["action"] == "approuver"
    assert corps["statut_global"] == "terminee"

    await db_session.refresh(etape)
    await db_session.refresh(demande)
    assert etape.statut == StatutEtape.APPROUVE
    # Ecart corrige (revue du 15/09) : la consommation vit desormais sur le
    # jeton lui-meme (table jetons_decision, §9.3), plus sur EtapeWorkflow.
    from sqlalchemy import select as _select

    from app.models.jeton_decision import JetonDecision

    ligne_jeton = (
        await db_session.execute(_select(JetonDecision).where(JetonDecision.etape_workflow_id == etape.id))
    ).scalars().one()
    assert ligne_jeton.utilise_a is not None
    assert demande.statut_global == StatutDemande.TERMINEE


async def test_refus_sans_commentaire_est_rejete(client, db_session):
    _, etape, manager, _, _employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "refuser", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)

    assert reponse.status_code == 422


async def test_refus_avec_commentaire_est_accepte(client, db_session):
    demande, etape, manager, _, _employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "refuser", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(
        f"/api/v1/decisions/{jeton}",
        json={"commentaire": "Effectif insuffisant sur cette période."},
        headers=entete,
    )

    assert reponse.status_code == 200
    assert reponse.json()["statut_global"] == "refusee"


async def test_jeton_deja_utilise_est_rejete_avec_un_conflit(client, db_session):
    _, etape, manager, _, _employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    premiere = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)
    assert premiere.status_code == 200

    seconde = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)
    assert seconde.status_code == 409


async def test_decision_par_un_autre_utilisateur_est_interdite(client, db_session):
    _, etape, _, autre_utilisateur, _employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(autre_utilisateur.id))}"}

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)

    assert reponse.status_code == 403


async def test_decision_sans_session_est_refusee_quand_loption_b_est_active(client, db_session):
    _, etape, _, _, _employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={})

    assert reponse.status_code == 401


async def test_jeton_invalide_est_rejete(client, db_session):
    reponse = await client.post("/api/v1/decisions/ceci-nest-pas-un-jeton", json={})
    assert reponse.status_code == 401


# --- Écart intégré (bug corrigé) : le solde est réellement décrémenté -------

async def test_approbation_consomme_reellement_le_solde(client, db_session, _mock_effets_de_bord):
    demande, etape, manager, _, employe, type_conge, drh = await _preparer_demande_en_attente(
        db_session, solde_jours=10
    )
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)
    assert reponse.status_code == 200

    from app.services.extensions.verrou_rh import obtenir_solde

    solde = await obtenir_solde(db_session, employe.id, type_conge.id, 2026)
    assert float(solde.solde_jours) == 7  # 10 - 3 jours (01-03 juin)
    assert float(solde.jours_pris) == 3

    # Ecart intégré : notification automatique de la DRH (approbation ET refus).
    destinataires = [appel.kwargs["destinataire"] for appel in _mock_effets_de_bord.await_args_list]
    assert drh.email in destinataires

    # Ecart identifié et corrigé (revue du 15/09) : le demandeur lui-même
    # doit aussi être notifié de l'issue de sa demande (CDC fonctionnel :
    # le demandeur doit être informé de l'issue de sa propre demande).
    assert employe.email in destinataires


async def test_approbation_notifie_le_demandeur_de_lissue(client, db_session, _mock_effets_de_bord):
    demande, etape, manager, _, employe, _type_conge, _drh = await _preparer_demande_en_attente(
        db_session, solde_jours=10
    )
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)
    assert reponse.status_code == 200

    appels_au_demandeur = [
        appel for appel in _mock_effets_de_bord.await_args_list if appel.kwargs["destinataire"] == employe.email
    ]
    assert len(appels_au_demandeur) == 1
    corps_demandeur = appels_au_demandeur[0].kwargs["corps_html"]
    assert "approuvée" in corps_demandeur
    # Ecart identifié et corrigé (revue du 15/09) : dates du congé concerné
    # et nom du décideur (le manager) désormais présents dans le corps.
    assert "01/06/2026" in corps_demandeur
    assert "03/06/2026" in corps_demandeur
    assert manager.nom_complet in corps_demandeur

    appels_a_la_drh = [
        appel for appel in _mock_effets_de_bord.await_args_list if appel.kwargs["destinataire"] == _drh.email
    ]
    assert len(appels_a_la_drh) == 1
    assert employe.nom_complet in appels_a_la_drh[0].kwargs["corps_html"]
    assert "01/06/2026" in appels_a_la_drh[0].kwargs["corps_html"]


async def test_refus_notifie_le_demandeur_avec_le_motif(client, db_session, _mock_effets_de_bord):
    demande, etape, manager, _, employe, _type_conge, _drh = await _preparer_demande_en_attente(
        db_session, solde_jours=10
    )
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "refuser", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(
        f"/api/v1/decisions/{jeton}",
        json={"commentaire": "Effectif insuffisant sur cette période."},
        headers=entete,
    )
    assert reponse.status_code == 200

    appels_au_demandeur = [
        appel for appel in _mock_effets_de_bord.await_args_list if appel.kwargs["destinataire"] == employe.email
    ]
    assert len(appels_au_demandeur) == 1
    corps_demandeur = appels_au_demandeur[0].kwargs["corps_html"]
    assert "Effectif insuffisant sur cette période." in corps_demandeur
    assert "01/06/2026" in corps_demandeur
    assert manager.nom_complet in corps_demandeur


async def test_refus_ne_consomme_pas_le_solde(client, db_session, _mock_effets_de_bord):
    demande, etape, manager, _, employe, type_conge, drh = await _preparer_demande_en_attente(
        db_session, solde_jours=10
    )
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "refuser", etape.approbateur_attendu_id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    reponse = await client.post(
        f"/api/v1/decisions/{jeton}", json={"commentaire": "Non justifié."}, headers=entete
    )
    assert reponse.status_code == 200

    from app.services.extensions.verrou_rh import obtenir_solde

    solde = await obtenir_solde(db_session, employe.id, type_conge.id, 2026)
    assert float(solde.solde_jours) == 10

    # La DRH est notifiée meme en cas de refus (visibilite RH sur toute decision).
    destinataires = [appel.kwargs["destinataire"] for appel in _mock_effets_de_bord.await_args_list]
    assert drh.email in destinataires
    # Ecart identifié et corrigé (revue du 15/09) : le demandeur aussi, meme en cas de refus.
    assert employe.email in destinataires


async def test_apercu_decision_expose_le_processus_et_ne_consomme_pas_le_jeton(client, db_session):
    """GET /decisions/{jeton} renseigne le frontend sans jamais consommer
    le jeton - verifie qu'un POST reste possible juste apres."""
    demande, etape, manager, _, employe, _type_conge, _drh = await _preparer_demande_en_attente(db_session)
    jeton = await decision_tokens.generer_jeton_decision(
        db_session, etape.id, "approuver", etape.approbateur_attendu_id
    )

    apercu = await client.get(f"/api/v1/decisions/{jeton}")

    assert apercu.status_code == 200
    corps = apercu.json()
    assert corps["action"] == "approuver"
    assert corps["processus"] == "conges"
    assert corps["est_derogation"] is False
    assert corps["demandeur_nom"] == employe.nom_complet
    assert corps["demande_id"] == str(demande.id)
    assert corps["statut_demande"] == "en_cours"
    assert "date_debut" in corps["resume"]

    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    decision = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)
    assert decision.status_code == 200


async def test_apercu_decision_jeton_invalide_renvoie_401(client):
    reponse = await client.get("/api/v1/decisions/jeton-qui-nexiste-pas")
    assert reponse.status_code == 401
