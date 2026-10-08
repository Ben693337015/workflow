"""
Test d'intégration - API "Demande de congés" (flux complet, section 13.2),
étendue avec les écarts intégrés : type de congé structuré, jours fériés,
modification, annulation, régularisation.
"""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.demande import Demande
from app.models.enums import RoleEtape, RoleUtilisateur, StatutDemande, StatutEtape, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.jour_ferie import JourFerie
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur


async def _preparer_type_conge(db_session):
    type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.flush()
    return type_conge


async def _preparer_employe_et_manager(db_session, solde_jours: float, type_conge=None, suffixe: str = ""):
    if type_conge is None:
        type_conge = await _preparer_type_conge(db_session)

    manager = Utilisateur(
        email=f"manager{suffixe}@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Manager Test",
        service="Support",
        role=RoleUtilisateur.MANAGER,
    )
    db_session.add(manager)
    await db_session.flush()

    employe = Utilisateur(
        email=f"employe{suffixe}@example.com",
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
    await db_session.commit()

    return employe, manager, type_conge


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    """Evite tout appel reseau reel vers Resend pendant les tests."""
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.conges.email_service.envoyer_email", mock)
    return mock


async def test_soumission_conges_avec_solde_suffisant(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-03",
        },
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["nombre_jours"] == 3
    assert corps["statut_global"] == "en_cours"

    import uuid as _uuid

    demande = await db_session.get(Demande, _uuid.UUID(corps["id"]))
    assert demande is not None
    assert demande.demandeur_id == employe.id
    assert demande.initiee_par_id == employe.id

    resultat_etapes = await db_session.execute(
        select(EtapeWorkflow).where(EtapeWorkflow.demande_id == demande.id)
    )
    etapes = resultat_etapes.scalars().all()
    assert len(etapes) == 1
    assert etapes[0].approbateur_attendu_id == manager.id

    _mock_envoi_email.assert_awaited_once()
    # Ecart identifié corrigé : le lien de décision pointait vers un domaine
    # factice codé en dur ("exemple.tld") - vérifie qu'il pointe désormais
    # vers le frontend réellement configuré, et que le jeton y figure bien.
    from app.core.config import get_settings

    corps_html_envoye = _mock_envoi_email.await_args.kwargs["corps_html"]
    assert get_settings().frontend_base_url in corps_html_envoye
    assert "exemple.tld" not in corps_html_envoye
    assert "/decisions/" in corps_html_envoye

    # Ecart identifié et corrigé (revue du 15/09) : le corps ne mentionnait
    # ni le nom du demandeur ni les dates - le manager devait cliquer pour
    # savoir qui demandait quoi et pour quand.
    assert employe.nom_complet in corps_html_envoye
    assert "01/06/2026" in corps_html_envoye
    assert "03/06/2026" in corps_html_envoye
    assert employe.nom_complet in _mock_envoi_email.await_args.kwargs["sujet"]

    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_avec_commentaire_est_stockee_et_transmise_au_manager(client, db_session, _mock_envoi_email):
    """Ecart identifié et corrigé (revue du 16/09) : champ absent du formulaire jusqu'ici."""
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-03",
            "commentaire": "Pose à cheval sur le pont du 1er mai.",
        },
    )
    assert reponse.status_code == 201

    r = await client.get("/api/v1/conges/")
    donnees = r.json()[0]["donnees"]
    assert donnees["commentaire"] == "Pose à cheval sur le pont du 1er mai."

    corps_html_envoye = _mock_envoi_email.await_args.kwargs["corps_html"]
    assert "Pose à cheval sur le pont du 1er mai." in corps_html_envoye
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_sans_commentaire_fonctionne_normalement(client, db_session, _mock_envoi_email):
    """Le commentaire est facultatif - ne doit rien casser quand il est absent."""
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    assert reponse.status_code == 201

    r = await client.get("/api/v1/conges/")
    assert r.json()[0]["donnees"].get("commentaire") is None
    assert "Commentaire du demandeur" not in _mock_envoi_email.await_args.kwargs["corps_html"]
    app.dependency_overrides.pop(get_current_user, None)


async def test_commentaire_est_echappe_dans_lemail_au_manager(client, db_session, _mock_envoi_email):
    """
    Ecart évité (revue du 16/09) : le commentaire est un texte libre saisi
    par l'employé, inséré dans du HTML envoyé par e-mail - même principe
    d'échappement que la fiche de confirmation (documents.py).
    """
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-03",
            "commentaire": "<b>test</b> & <script>alert(1)</script>",
        },
    )
    assert reponse.status_code == 201

    corps_html_envoye = _mock_envoi_email.await_args.kwargs["corps_html"]
    assert "<script>" not in corps_html_envoye
    assert "&lt;script&gt;" in corps_html_envoye
    app.dependency_overrides.pop(get_current_user, None)


async def test_commentaire_avec_uniquement_des_espaces_est_normalise_a_null(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-03",
            "commentaire": "   ",
        },
    )
    assert reponse.status_code == 201
    r = await client.get("/api/v1/conges/")
    assert r.json()[0]["donnees"].get("commentaire") is None
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_conges_avec_solde_insuffisant_est_rejetee(client, db_session, _mock_envoi_email):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=1)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-05",
        },
    )

    assert reponse.status_code == 422
    resultat = await db_session.execute(select(Demande))
    assert resultat.scalars().all() == []
    _mock_envoi_email.assert_not_awaited()
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_conges_avec_dates_incoherentes_est_rejetee_par_le_schema(
    client, db_session, _mock_envoi_email
):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-05",
            "date_fin": "2026-06-01",
        },
    )

    assert reponse.status_code == 422
    _mock_envoi_email.assert_not_awaited()
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_avec_type_conge_inconnu_est_rejetee(client, db_session, _mock_envoi_email):
    employe, _, _ = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    import uuid as _uuid

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(_uuid.uuid4()),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-03",
        },
    )

    assert reponse.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_exclut_les_jours_feries_du_decompte(client, db_session, _mock_envoi_email):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=4)
    from datetime import date

    db_session.add(JourFerie(nom="Jour férié", date=date(2026, 6, 2), recurrent=False))
    await db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-05",
        },
    )

    assert reponse.status_code == 201
    assert reponse.json()["nombre_jours"] == 4  # 5 jours calendaires - 1 férié
    app.dependency_overrides.pop(get_current_user, None)


async def test_lister_mes_demandes_retourne_les_demandes_du_demandeur_uniquement(
    client, db_session, _mock_envoi_email
):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-02"},
    )
    await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-07-01", "date_fin": "2026-07-02"},
    )

    reponse = await client.get("/api/v1/conges/")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 2
    # Les plus récentes d'abord.
    assert corps[0]["donnees"]["date_debut"] == "2026-07-01"
    app.dependency_overrides.pop(get_current_user, None)


async def test_lister_mes_demandes_nexpose_pas_les_demandes_dun_autre_employe(
    client, db_session, _mock_envoi_email
):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe
    await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-02"},
    )

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.get("/api/v1/conges/")

    assert reponse.status_code == 200
    assert reponse.json() == []
    app.dependency_overrides.pop(get_current_user, None)

# --- Écart intégré : modification d'une demande en attente ------------------

async def test_modifier_une_demande_en_cours_met_a_jour_les_dates(client, db_session, _mock_envoi_email):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]

    reponse = await client.patch(
        f"/api/v1/conges/{demande_id}", json={"date_fin": "2026-06-04"}
    )

    assert reponse.status_code == 200
    assert reponse.json()["nombre_jours"] == 4
    app.dependency_overrides.pop(get_current_user, None)


async def test_modifier_une_demande_en_cours_met_a_jour_le_commentaire(client, db_session, _mock_envoi_email):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={
            "type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03",
            "commentaire": "Premier commentaire.",
        },
    )
    demande_id = creation.json()["id"]

    reponse = await client.patch(f"/api/v1/conges/{demande_id}", json={"commentaire": "Commentaire mis à jour."})

    assert reponse.status_code == 200
    assert reponse.json()["donnees"]["commentaire"] == "Commentaire mis à jour."
    app.dependency_overrides.pop(get_current_user, None)


async def test_modifier_une_demande_dun_autre_utilisateur_est_interdit(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe
    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.patch(f"/api/v1/conges/{demande_id}", json={"date_fin": "2026-06-04"})

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


# --- Écart intégré : annulation d'une demande en attente --------------------

async def test_annuler_une_demande_en_cours(client, db_session, _mock_envoi_email):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe
    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]

    reponse = await client.post(f"/api/v1/conges/{demande_id}/annuler")

    assert reponse.status_code == 200
    assert reponse.json()["statut_global"] == "annulee"
    app.dependency_overrides.pop(get_current_user, None)


async def test_le_jeton_dune_demande_annulee_ne_peut_plus_decider(client, db_session, _mock_envoi_email):
    import uuid

    from app.services import decision_tokens

    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe
    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]
    etape_id = creation.json()["premiere_etape_id"]
    await client.post(f"/api/v1/conges/{demande_id}/annuler")
    app.dependency_overrides.pop(get_current_user, None)

    jeton = await decision_tokens.generer_jeton_decision(db_session, uuid.UUID(etape_id), "approuver", manager.id)
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    reponse = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete)

    assert reponse.status_code == 409


# --- Écart intégré : régularisation par un manager --------------------------

async def test_regularisation_approuvee_par_le_manager_consomme_le_solde(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/conges/regularisation",
        json={
            "employe_id": str(employe.id),
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-02",
            "action": "approuver",
        },
    )

    assert reponse.status_code == 201
    assert reponse.json()["statut_global"] == "terminee"

    from app.services.extensions.verrou_rh import obtenir_solde

    solde = await obtenir_solde(db_session, employe.id, type_conge.id, 2026)
    assert float(solde.solde_jours) == 8  # 10 - 2 jours régularisés

    # Ecart identifié et corrigé (revue du 15/09) : l'employé concerné doit
    # être notifié qu'une régularisation a été actée en son nom - jusqu'ici
    # silencieuse pour lui.
    destinataires = [appel.kwargs["destinataire"] for appel in _mock_envoi_email.await_args_list]
    assert employe.email in destinataires
    # Deuxieme ecart corrige dans la meme revue : les dates precises de
    # l'absence regularisee et le nom du manager doivent figurer dans le corps.
    appel_employe = next(a for a in _mock_envoi_email.await_args_list if a.kwargs["destinataire"] == employe.email)
    assert "01/06/2026" in appel_employe.kwargs["corps_html"]
    assert "02/06/2026" in appel_employe.kwargs["corps_html"]
    assert manager.nom_complet in appel_employe.kwargs["corps_html"]
    app.dependency_overrides.pop(get_current_user, None)


async def test_regularisation_refusee_exige_un_commentaire(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/conges/regularisation",
        json={
            "employe_id": str(employe.id),
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-02",
            "action": "refuser",
        },
    )

    assert reponse.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_regularisation_refusee_notifie_lemploye_avec_le_motif(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/conges/regularisation",
        json={
            "employe_id": str(employe.id),
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-02",
            "action": "refuser",
            "commentaire": "Absence non justifiée.",
        },
    )

    assert reponse.status_code == 201
    appels_au_demandeur = [
        appel for appel in _mock_envoi_email.await_args_list if appel.kwargs["destinataire"] == employe.email
    ]
    assert len(appels_au_demandeur) == 1
    corps = appels_au_demandeur[0].kwargs["corps_html"]
    assert "Absence non justifiée." in corps
    # Ecart identifié et corrigé (revue du 15/09) : dates et decideur absents
    # du corps sur la branche refus de la regularisation.
    assert "01/06/2026" in corps
    assert "02/06/2026" in corps
    assert manager.nom_complet in corps
    app.dependency_overrides.pop(get_current_user, None)


async def test_regularisation_par_un_simple_employe_est_interdite(client, db_session, _mock_envoi_email):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.post(
        "/api/v1/conges/regularisation",
        json={
            "employe_id": str(employe.id),
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-02",
            "action": "approuver",
        },
    )

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_un_manager_sans_manager_associe_peut_se_regulariser_lui_meme(
    client, db_session, _mock_envoi_email
):
    """
    Demande explicite : un manager sans aucun manager associé (personne
    au-dessus de lui dans la hiérarchie pour décider via le circuit normal)
    doit pouvoir régulariser sa propre absence. Vérifie le flux complet
    (pas seulement la présence dans /mon-equipe, déjà couverte dans
    test_utilisateurs_api.py) : la route de régularisation elle-même
    accepte employe_id == current_user.id et consomme bien le solde du
    manager, pas celui de quelqu'un d'autre.
    """
    _, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    assert manager.manager_id is None  # scenario exact de la demande

    db_session.add(
        SoldeConges(
            utilisateur_id=manager.id,
            type_conge_id=type_conge.id,
            solde_jours=10,
            jours_acquis=10,
            jours_pris=0,
            exercice=2026,
        )
    )
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/conges/regularisation",
        json={
            "employe_id": str(manager.id),
            "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01",
            "date_fin": "2026-06-02",
            "action": "approuver",
        },
    )

    assert reponse.status_code == 201
    assert reponse.json()["statut_global"] == "terminee"

    from app.services.extensions.verrou_rh import obtenir_solde

    solde = await obtenir_solde(db_session, manager.id, type_conge.id, 2026)
    assert float(solde.solde_jours) == 8  # 10 - 2 jours régularisés
    app.dependency_overrides.pop(get_current_user, None)


# --- Écart intégré : fiche de confirmation d'absence (fin de circuit) ------

async def test_telecharger_fiche_confirmation_pour_une_demande_approuvee(
    client, db_session, _mock_envoi_email
):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
        statut_global=StatutDemande.TERMINEE,
    )
    db_session.add(demande)
    await db_session.commit()
    await db_session.refresh(demande)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.get(f"/api/v1/conges/{demande.id}/fiche-confirmation")

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/pdf"
    assert reponse.content[:4] == b"%PDF"
    app.dependency_overrides.pop(get_current_user, None)


async def test_fiche_confirmation_mentionne_le_manager_qui_a_approuve(
    client, db_session, _mock_envoi_email
):
    """
    Écart intégré : la fiche doit mentionner le manager qui a réellement
    approuvé la demande (bloc de signature), pas juste l'employé.
    """
    import subprocess
    from datetime import UTC, datetime

    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
        statut_global=StatutDemande.TERMINEE,
    )
    db_session.add(demande)
    await db_session.flush()

    etape = EtapeWorkflow(
        demande_id=demande.id,
        niveau=1,
        role=RoleEtape.APPROBATEUR,
        approbateur_attendu_id=manager.id,
        statut=StatutEtape.APPROUVE,
        date_reponse=datetime(2026, 6, 2, 9, 15, tzinfo=UTC),
    )
    db_session.add(etape)
    await db_session.commit()
    await db_session.refresh(demande)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.get(f"/api/v1/conges/{demande.id}/fiche-confirmation")
    assert reponse.status_code == 200

    texte = subprocess.run(
        ["pdftotext", "-", "-"], input=reponse.content, capture_output=True, check=True
    ).stdout.decode()

    assert manager.nom_complet in texte
    assert "02/06/2026" in texte
    app.dependency_overrides.pop(get_current_user, None)


async def test_fiche_confirmation_indisponible_si_demande_pas_approuvee(
    client, db_session, _mock_envoi_email
):
    employe, _, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]

    reponse = await client.get(f"/api/v1/conges/{demande_id}/fiche-confirmation")

    assert reponse.status_code == 409
    app.dependency_overrides.pop(get_current_user, None)


async def test_fiche_confirmation_interdite_a_un_tiers(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    autre_manager, _, _ = await _preparer_employe_et_manager(
        db_session, solde_jours=10, type_conge=type_conge, suffixe="2"
    )

    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=employe.id,
        initiee_par_id=employe.id,
        donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
        statut_global=StatutDemande.TERMINEE,
    )
    db_session.add(demande)
    await db_session.commit()
    await db_session.refresh(demande)

    app.dependency_overrides[get_current_user] = lambda: autre_manager
    reponse = await client.get(f"/api/v1/conges/{demande.id}/fiche-confirmation")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


# --- Écart intégré : agenda de l'équipe (fin de circuit) --------------------

async def test_agenda_equipe_liste_les_absences_approuvees_du_manager(
    client, db_session, _mock_envoi_email
):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)

    demande_approuvee = Demande(
        processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id,
        donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
        statut_global=StatutDemande.TERMINEE,
    )
    demande_en_cours = Demande(
        processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id,
        donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-07-01", "date_fin": "2026-07-03"},
        statut_global=StatutDemande.EN_COURS,
    )
    db_session.add_all([demande_approuvee, demande_en_cours])
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: manager
    reponse = await client.get("/api/v1/conges/agenda-equipe")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 1  # seule la demande TERMINEE apparait
    assert corps[0]["employe_nom"] == employe.nom_complet
    assert corps[0]["date_debut"] == "2026-06-01"
    app.dependency_overrides.pop(get_current_user, None)


async def test_agenda_equipe_interdit_a_un_simple_employe(client, db_session, _mock_envoi_email):
    employe, _, _ = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    reponse = await client.get("/api/v1/conges/agenda-equipe")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_agenda_equipe_drh_voit_plusieurs_equipes(client, db_session, _mock_envoi_email):
    employe_1, manager_1, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    employe_2, manager_2, _ = await _preparer_employe_et_manager(
        db_session, solde_jours=10, type_conge=type_conge, suffixe="2"
    )

    for employe in (employe_1, employe_2):
        db_session.add(Demande(
            processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id,
            donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-02"},
            statut_global=StatutDemande.TERMINEE,
        ))
    from app.core.security import hash_password

    drh = Utilisateur(
        email="drh-agenda@example.com", mot_de_passe_hash=hash_password("x"),
        nom_complet="DRH Test", service="RH", role=RoleUtilisateur.DRH,
    )
    db_session.add(drh)
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: drh
    reponse = await client.get("/api/v1/conges/agenda-equipe")

    assert reponse.status_code == 200
    assert len(reponse.json()) == 2  # les deux equipes, tous managers confondus
    app.dependency_overrides.pop(get_current_user, None)


# --- Relance manuelle de notification (écart identifié et corrigé, revue
# du 16/09, suite au test réel de bout en bout). --------------------------


async def test_le_demandeur_peut_relancer_la_notification(client, db_session, _mock_envoi_email):
    from app.services import decision_tokens

    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]
    n_emails_avant = len(_mock_envoi_email.await_args_list)

    reponse = await client.post(f"/api/v1/conges/{demande_id}/relancer")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["email_envoye"] is True
    assert len(_mock_envoi_email.await_args_list) == n_emails_avant + 1
    email_relance = _mock_envoi_email.await_args_list[-1]
    assert email_relance.kwargs["destinataire"] == manager.email
    assert "Rappel" in email_relance.kwargs["sujet"]
    app.dependency_overrides.pop(get_current_user, None)


async def test_relance_revoque_lancien_jeton_et_en_emet_un_nouveau(client, db_session, _mock_envoi_email):
    import re

    from app.core.security import create_access_token

    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]
    premier_email = _mock_envoi_email.await_args_list[-1]
    ancien_jeton = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", premier_email.kwargs["corps_html"]).group(1)

    reponse = await client.post(f"/api/v1/conges/{demande_id}/relancer")
    assert reponse.status_code == 200
    nouveau_email = _mock_envoi_email.await_args_list[-1]
    nouveau_jeton = re.search(
        r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", nouveau_email.kwargs["corps_html"]
    ).group(1)
    assert nouveau_jeton != ancien_jeton
    app.dependency_overrides.pop(get_current_user, None)

    # L'ancien jeton (celui du premier e-mail) doit maintenant être revoque.
    entete_manager = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    reponse_ancien = await client.post(f"/api/v1/decisions/{ancien_jeton}", json={}, headers=entete_manager)
    assert reponse_ancien.status_code == 401

    reponse_nouveau = await client.post(f"/api/v1/decisions/{nouveau_jeton}", json={}, headers=entete_manager)
    assert reponse_nouveau.status_code == 200


async def test_relance_est_interdite_a_un_tiers(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    autre_employe, _, _ = await _preparer_employe_et_manager(
        db_session, solde_jours=10, type_conge=type_conge, suffixe="2"
    )
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]
    app.dependency_overrides[get_current_user] = lambda: autre_employe

    reponse = await client.post(f"/api/v1/conges/{demande_id}/relancer")

    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_relance_refusee_si_la_demande_nest_plus_en_cours(client, db_session, _mock_envoi_email):
    import re

    from app.core.security import create_access_token

    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=10)
    app.dependency_overrides[get_current_user] = lambda: employe

    creation = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )
    demande_id = creation.json()["id"]
    email_manager = _mock_envoi_email.await_args_list[-1]
    jeton = re.search(r"/decisions/([A-Za-z0-9_\-\.]+)'>Approuver", email_manager.kwargs["corps_html"]).group(1)
    app.dependency_overrides.pop(get_current_user, None)

    entete_manager = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}
    reponse_decision = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=entete_manager)
    assert reponse_decision.status_code == 200

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(f"/api/v1/conges/{demande_id}/relancer")

    assert reponse.status_code == 409
    app.dependency_overrides.pop(get_current_user, None)
