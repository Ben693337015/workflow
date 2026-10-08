"""
Tests d'integration de l'espace de communication bidirectionnelle (ecart
n°5, section 4.5 du CDC fonctionnel) : suspension d'une decision pour
demander des precisions, echange de messages, reprise du circuit.
Applique au processus congés ici (le mécanisme est générique, agnostique
du processus - voir app/routers/clarifications.py).
"""
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, manager_id=None, email=None, service="Support"):
    utilisateur = Utilisateur(
        email=email or f"{role.value}-{manager_id}@example.com",
        mot_de_passe_hash="hash",
        nom_complet=f"Test {role.value}",
        service=service,
        role=role,
        manager_id=manager_id,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def _preparer_conges(db_session):
    manager = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER)
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    type_conge = TypeConge(code="CP", nom="Congé payé", taux_acquisition_jours_mois=2.08)
    db_session.add(type_conge)
    await db_session.flush()
    db_session.add(
        SoldeConges(
            utilisateur_id=employe.id,
            type_conge_id=type_conge.id,
            solde_jours=10,
            jours_acquis=10,
            jours_pris=0,
            exercice=2026,
        )
    )
    await db_session.commit()
    return employe, manager, type_conge


def _entete(utilisateur):
    return {"Authorization": f"Bearer {create_access_token(str(utilisateur.id))}"}


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.clarifications.email_service.envoyer_email", mock)
    monkeypatch.setattr("app.routers.conges.email_service.envoyer_email", mock)
    monkeypatch.setattr("app.routers.decisions.email_service.envoyer_email", mock)
    return mock


async def _soumettre_conges(client, employe, type_conge):
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        reponse = await client.post(
            "/api/v1/conges/",
            json={
                "type_conge_id": str(type_conge.id),
                "date_debut": "2026-06-01",
                "date_fin": "2026-06-02",
            },
        )
    finally:
        # Essentiel : sans ce nettoyage, l'override reste actif pour tous
        # les appels suivants du meme test, qui ignoreraient alors
        # silencieusement les en-tetes Authorization passes a client.post
        # et utiliseraient toujours `employe` - bug reel trouve en
        # ecrivant ces tests (voir le recit de la revue du 27/09).
        app.dependency_overrides.pop(get_current_user, None)
    assert reponse.status_code == 201
    return reponse.json()["id"]


async def test_le_manager_peut_suspendre_pour_demander_des_precisions(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)

    reponse = await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "Le justificatif médical est illisible, pouvez-vous le renvoyer ?"},
        headers=_entete(manager),
    )

    assert reponse.status_code == 201
    assert reponse.json()["auteur_nom"] == manager.nom_complet

    from sqlalchemy import select

    from app.models.demande import Demande
    import uuid as uuid_module

    demande = await db_session.get(Demande, uuid_module.UUID(demande_id))
    assert demande.statut_global == "complement_demande"


async def test_seul_lapprobateur_attendu_peut_suspendre(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)

    reponse = await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "test"},
        headers=_entete(employe),  # le demandeur, pas l'approbateur
    )

    assert reponse.status_code == 403


async def test_decision_impossible_pendant_la_suspension(client, db_session):
    """Le refus/l'approbation via l'ancien jeton doit être bloqué tant que
    la demande est en attente de précisions - vérifié réellement, pas supposé."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.models.jeton_decision import JetonDecision
    import uuid as uuid_module

    etape = (
        await db_session.execute(
            select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid_module.UUID(demande_id))
        )
    ).scalar_one()
    jeton_row = (
        await db_session.execute(
            select(JetonDecision).where(
                JetonDecision.etape_workflow_id == etape.id,
                JetonDecision.action_autorisee == "approuver",
            )
        )
    ).scalar_one()

    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "précisions svp"},
        headers=_entete(manager),
    )

    # On ne peut pas rejouer le jeton en clair (jamais stocke) : on en
    # regenere un pour la meme etape, avec la meme action, pour verifier
    # que le STATUT DE L'ETAPE (pas seulement le jeton) bloque la decision.
    from app.services import decision_tokens

    nouveau_jeton = await decision_tokens.generer_jeton_decision(
        db_session, etape.id, "approuver", manager.id
    )
    await db_session.commit()

    reponse = await client.post(f"/api/v1/decisions/{nouveau_jeton}", json={}, headers=_entete(manager))

    assert reponse.status_code == 409
    assert "précisions" in reponse.json()["detail"].lower()


async def test_echange_de_messages_entre_demandeur_et_approbateur(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)

    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "Le justificatif est illisible."},
        headers=_entete(manager),
    )

    reponse_employe = await client.post(
        f"/api/v1/demandes/{demande_id}/messages",
        json={"contenu": "Voici une version plus lisible, en pièce jointe de mon prochain e-mail."},
        headers=_entete(employe),
    )
    assert reponse_employe.status_code == 201

    reponse_liste = await client.get(f"/api/v1/demandes/{demande_id}/messages", headers=_entete(manager))
    assert reponse_liste.status_code == 200
    messages = reponse_liste.json()
    assert len(messages) == 2  # le message de suspension + la reponse
    assert messages[0]["auteur_nom"] == manager.nom_complet
    assert messages[1]["auteur_nom"] == employe.nom_complet


async def test_un_tiers_ne_peut_ni_lire_ni_ecrire_dans_la_discussion(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    autre_manager = await _creer_utilisateur(
        db_session, RoleUtilisateur.MANAGER, email="autre-manager@example.com"
    )
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "précisions svp"},
        headers=_entete(manager),
    )

    reponse_lecture = await client.get(
        f"/api/v1/demandes/{demande_id}/messages", headers=_entete(autre_manager)
    )
    reponse_ecriture = await client.post(
        f"/api/v1/demandes/{demande_id}/messages",
        json={"contenu": "je m'invite"},
        headers=_entete(autre_manager),
    )

    assert reponse_lecture.status_code == 403
    assert reponse_ecriture.status_code == 403


async def test_message_impossible_hors_suspension(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    # Pas de suspension : la demande est encore simplement "en_cours".

    reponse = await client.post(
        f"/api/v1/demandes/{demande_id}/messages",
        json={"contenu": "bonjour"},
        headers=_entete(employe),
    )

    assert reponse.status_code == 409


async def test_reprise_par_lapprobateur_puis_decision_possible(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "précisions svp"},
        headers=_entete(manager),
    )

    reprise = await client.post(f"/api/v1/demandes/{demande_id}/reprendre", headers=_entete(manager))
    assert reprise.status_code == 200
    assert reprise.json()["statut_global"] == "en_cours"

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.services import decision_tokens
    import uuid as uuid_module

    etape = (
        await db_session.execute(
            select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid_module.UUID(demande_id))
        )
    ).scalar_one()
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", manager.id)
    await db_session.commit()

    decision = await client.post(f"/api/v1/decisions/{jeton}", json={}, headers=_entete(manager))
    assert decision.status_code == 200
    assert decision.json()["statut_global"] == "terminee"


async def test_seul_lapprobateur_peut_reprendre(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "précisions svp"},
        headers=_entete(manager),
    )

    reponse = await client.post(f"/api/v1/demandes/{demande_id}/reprendre", headers=_entete(employe))

    assert reponse.status_code == 403


async def test_apercu_du_jeton_reste_lisible_pendant_la_suspension_et_expose_le_statut(client, db_session):
    """La page de decision doit pouvoir afficher la discussion en cours (et
    le bouton de reprise) depuis le meme lien e-mail que l'approbateur a deja
    recu - donc GET /decisions/{jeton} ne doit pas echouer une fois suspendu."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.services import decision_tokens
    import uuid as uuid_module

    etape = (
        await db_session.execute(
            select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid_module.UUID(demande_id))
        )
    ).scalar_one()
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", manager.id)
    await db_session.commit()

    avant = await client.get(f"/api/v1/decisions/{jeton}")
    assert avant.json()["statut_demande"] == "en_cours"
    assert avant.json()["demande_id"] == demande_id

    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre",
        json={"message": "précisions svp"},
        headers=_entete(manager),
    )

    pendant = await client.get(f"/api/v1/decisions/{jeton}")
    assert pendant.status_code == 200
    assert pendant.json()["statut_demande"] == "complement_demande"


# --- Verification approfondie de la communication bidirectionnelle (27/09) ---

_INJECTION = '<a href="http://evil.example/login">Cliquez ici</a><script>alert(1)</script>'


def _corps_emails(mock):
    return [appel.kwargs["corps_html"] for appel in mock.call_args_list]


async def test_message_de_suspension_est_echappe_dans_lemail_au_demandeur(client, db_session, _mock_envoi_email):
    """Un texte saisi ne doit jamais devenir du HTML actif dans l'e-mail du destinataire."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    _mock_envoi_email.reset_mock()

    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": _INJECTION}, headers=_entete(manager)
    )

    corps = " ".join(_corps_emails(_mock_envoi_email))
    assert 'href="http://evil.example' not in corps
    assert "<script>" not in corps
    assert "&lt;script&gt;" in corps


async def test_reponse_du_demandeur_est_echappee_dans_lemail_a_lapprobateur(client, db_session, _mock_envoi_email):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "précisions svp"}, headers=_entete(manager)
    )
    _mock_envoi_email.reset_mock()

    await client.post(
        f"/api/v1/demandes/{demande_id}/messages", json={"contenu": _INJECTION}, headers=_entete(employe)
    )

    corps = " ".join(_corps_emails(_mock_envoi_email))
    assert 'href="http://evil.example' not in corps
    assert "<script>" not in corps


async def test_le_demandeur_peut_annuler_sa_demande_pendant_la_suspension(client, db_session):
    """Sinon une demande suspendue est un piege : ni decidable, ni retirable."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "précisions svp"}, headers=_entete(manager)
    )

    reponse = await client.post(f"/api/v1/conges/{demande_id}/annuler", headers=_entete(employe))

    assert reponse.status_code == 200
    assert reponse.json()["statut_global"] == "annulee"


# --- Pieces complementaires deposees dans la discussion (CDC section 4.5) ---


async def _suspendre(client, manager, demande_id):
    reponse = await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "Justificatif illisible."}, headers=_entete(manager)
    )
    assert reponse.status_code == 201


def _avec_fichier(client, demande_id, utilisateur, contenu="Voici la pièce.", nom="justificatif.pdf",
                  octets=b"%PDF-1.4 piece", type_mime="application/pdf"):
    return client.post(
        f"/api/v1/demandes/{demande_id}/messages/avec-fichier",
        data={"contenu": contenu},
        files={"fichier": (nom, octets, type_mime)},
        headers=_entete(utilisateur),
    )


async def test_le_demandeur_depose_une_piece_et_lapprobateur_la_telecharge_a_lidentique(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await _suspendre(client, manager, demande_id)
    octets = bytes(range(256)) * 4  # octets non textuels

    envoi = await _avec_fichier(client, demande_id, employe, octets=b"%PDF" + octets)
    assert envoi.status_code == 201
    assert envoi.json()["fichier_nom"] == "justificatif.pdf"

    liste = await client.get(f"/api/v1/demandes/{demande_id}/messages", headers=_entete(manager))
    avec_piece = [m for m in liste.json() if m["fichier_nom"]]
    assert len(avec_piece) == 1
    assert [m["fichier_nom"] for m in liste.json()].count(None) == 1  # le message de suspension n'a pas de piece

    telechargement = await client.get(
        f"/api/v1/demandes/{demande_id}/messages/{avec_piece[0]['id']}/fichier", headers=_entete(manager)
    )
    assert telechargement.status_code == 200
    assert telechargement.content == b"%PDF" + octets


async def test_lapprobateur_peut_aussi_deposer_une_piece(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await _suspendre(client, manager, demande_id)

    envoi = await _avec_fichier(client, demande_id, manager, contenu="Modèle attendu en pièce jointe.")

    assert envoi.status_code == 201


async def test_depot_de_piece_refuse_hors_suspension_tiers_type_invalide_et_fichier_vide(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    autre = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, email="tiers@example.com")
    demande_id = await _soumettre_conges(client, employe, type_conge)

    hors_suspension = await _avec_fichier(client, demande_id, employe)
    assert hors_suspension.status_code == 409

    await _suspendre(client, manager, demande_id)
    assert (await _avec_fichier(client, demande_id, autre)).status_code == 403
    exe = await _avec_fichier(client, demande_id, employe, nom="virus.exe", type_mime="application/x-msdownload")
    assert exe.status_code == 422
    vide = await _avec_fichier(client, demande_id, employe, octets=b"")
    assert vide.status_code == 422


async def test_un_tiers_ne_peut_pas_telecharger_une_piece_de_discussion(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    autre = await _creer_utilisateur(db_session, RoleUtilisateur.MANAGER, email="tiers2@example.com")
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await _suspendre(client, manager, demande_id)
    envoi = await _avec_fichier(client, demande_id, employe)

    reponse = await client.get(
        f"/api/v1/demandes/{demande_id}/messages/{envoi.json()['id']}/fichier", headers=_entete(autre)
    )

    assert reponse.status_code == 403


async def test_une_piece_ne_se_lit_pas_via_le_demande_id_dune_autre_demande(client, db_session):
    """Un participant de sa PROPRE demande ne doit pas lire la piece d'une autre
    en combinant son demande_id avec le message_id d'un tiers."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_a = await _soumettre_conges(client, employe, type_conge)
    await _suspendre(client, manager, demande_a)
    piece_a = (await _avec_fichier(client, demande_a, employe)).json()["id"]

    autre_employe = await _creer_utilisateur(
        db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id, email="autre-employe@example.com"
    )
    from sqlalchemy import select

    from app.models.solde_conges import SoldeConges

    db_session.add(
        SoldeConges(utilisateur_id=autre_employe.id, type_conge_id=type_conge.id, solde_jours=10,
                    jours_acquis=10, jours_pris=0, exercice=2026)
    )
    await db_session.commit()
    demande_b = await _soumettre_conges(client, autre_employe, type_conge)

    reponse = await client.get(
        f"/api/v1/demandes/{demande_b}/messages/{piece_a}/fichier", headers=_entete(autre_employe)
    )

    assert reponse.status_code == 404


async def test_nom_de_fichier_hostile_ne_corrompt_pas_lentete_de_telechargement(client, db_session):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await _suspendre(client, manager, demande_id)
    envoi = await _avec_fichier(client, demande_id, employe, nom='a"b;c.pdf')

    reponse = await client.get(
        f"/api/v1/demandes/{demande_id}/messages/{envoi.json()['id']}/fichier", headers=_entete(manager)
    )

    assert reponse.status_code == 200
    entete = reponse.headers["content-disposition"]
    assert "filename*=UTF-8''" in entete
    assert 'a"b' not in entete  # (httpx encode deja le guillemet en %22 : le serveur le re-encode, jamais brut)


# --- liens dans les e-mails de discussion (defaut constate en test reel, 05/10) -----------------------------
# Avant : « Répondez dans l'espace de discussion » sans AUCUN lien. Le destinataire ne savait pas ou aller.

import re


def _liens(mock):
    return re.findall(r"href='([^']+)'", " ".join(_corps_emails(mock)))


async def test_email_de_suspension_contient_un_lien_vers_les_demandes_du_demandeur(
    client, db_session, _mock_envoi_email
):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    _mock_envoi_email.reset_mock()

    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "précisions svp"}, headers=_entete(manager)
    )

    liens = _liens(_mock_envoi_email)
    assert len(liens) == 1 and liens[0].endswith("/mes-demandes")


async def test_reponse_du_demandeur_donne_a_lapprobateur_un_lien_de_decision_utilisable(
    client, db_session, _mock_envoi_email
):
    """Le lien recu par l'approbateur ouvre la page de decision (apercu lisible, statut « complement_demande »)."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "précisions svp"}, headers=_entete(manager)
    )
    _mock_envoi_email.reset_mock()

    await client.post(
        f"/api/v1/demandes/{demande_id}/messages", json={"contenu": "voici le motif"}, headers=_entete(employe)
    )

    liens = _liens(_mock_envoi_email)
    assert len(liens) == 1 and "/decisions/" in liens[0]
    jeton = liens[0].rsplit("/decisions/", 1)[1]
    apercu = await client.get(f"/api/v1/decisions/{jeton}", headers=_entete(manager))
    assert apercu.status_code == 200
    assert apercu.json()["statut_demande"] == "complement_demande"
    assert apercu.json()["demande_id"] == demande_id


async def test_une_reponse_ne_casse_pas_le_lien_deja_ouvert_par_lapprobateur(client, db_session, _mock_envoi_email):
    """
    Regression (05/10, test navigateur) : l'e-mail de reponse revoquait l'ancien lien. L'approbateur, qui avait
    la page ouverte avec ce lien, recevait un 401 au clic sur « Reprendre le workflow ».
    """
    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.services import decision_tokens
    import uuid as uuid_module

    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    etape = (
        await db_session.execute(select(EtapeWorkflow).where(EtapeWorkflow.demande_id == uuid_module.UUID(demande_id)))
    ).scalars().first()
    lien_ouvert = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", manager.id)
    await db_session.commit()
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "précisions svp"}, headers=_entete(manager)
    )

    jetons_recus = []
    for texte in ("premiere reponse", "seconde reponse"):
        _mock_envoi_email.reset_mock()
        await client.post(
            f"/api/v1/demandes/{demande_id}/messages", json={"contenu": texte}, headers=_entete(employe)
        )
        jetons_recus.append(_liens(_mock_envoi_email)[0].rsplit("/decisions/", 1)[1])
    reprise = await client.post(f"/api/v1/demandes/{demande_id}/reprendre", headers=_entete(manager))

    assert reprise.status_code == 200
    for jeton in [lien_ouvert, *jetons_recus]:
        apercu = await client.get(f"/api/v1/decisions/{jeton}", headers=_entete(manager))
        assert apercu.status_code == 200, "un lien deja emis ne doit pas etre invalide par la discussion"
        assert apercu.json()["statut_demande"] == "en_cours"


async def test_email_de_reponse_de_lapprobateur_pointe_vers_la_page_du_demandeur(
    client, db_session, _mock_envoi_email
):
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await client.post(
        f"/api/v1/demandes/{demande_id}/suspendre", json={"message": "précisions svp"}, headers=_entete(manager)
    )
    _mock_envoi_email.reset_mock()

    await client.post(
        f"/api/v1/demandes/{demande_id}/messages", json={"contenu": "et le dossier complet ?"}, headers=_entete(manager)
    )

    liens = _liens(_mock_envoi_email)
    assert len(liens) == 1 and liens[0].endswith("/mes-demandes")


async def test_piece_de_discussion_jusqu_a_30_mo_au_dela_refusee(client, db_session):
    """Passee de 10 a 30 Mo (05/10) puis 40 Mo (07/10) : 12 Mo accepte (refuse avant), 40 Mo + 1 octet refuse avec le bon message."""
    employe, manager, type_conge = await _preparer_conges(db_session)
    demande_id = await _soumettre_conges(client, employe, type_conge)
    await _suspendre(client, manager, demande_id)

    ok = await _avec_fichier(client, demande_id, employe, octets=b"%PDF" + b"0" * (12 * 1024 * 1024))
    assert ok.status_code == 201
    trop = await _avec_fichier(client, demande_id, employe, octets=b"%PDF" + b"0" * (40 * 1024 * 1024 - 3))
    assert trop.status_code == 422 and "40 Mo" in trop.json()["detail"]
