"""
Tests d'integration du processus "Validation d'achats et contrats"
(section 3 / 7 / 11 du CDC technique) : circuit fixe a deux niveaux (avis
du Service juridique, puis signature de la Direction generale) et suivi
budgetaire, sans manager (ecart avec conges/notes de frais).
"""
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur


async def _creer_utilisateur(db_session, role, email=None, service="Ventes", actif=True):
    utilisateur = Utilisateur(
        email=email or f"{role.value}@example.com",
        mot_de_passe_hash="hash",
        nom_complet=f"Test {role.value}",
        service=service,
        role=role,
        actif=actif,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


async def _creer_enveloppe(db_session, service, exercice, budget_alloue):
    enveloppe = EnveloppeBudgetaire(service=service, exercice=exercice, budget_alloue=budget_alloue)
    db_session.add(enveloppe)
    await db_session.commit()
    return enveloppe


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.achats.email_service.envoyer_email", mock)
    monkeypatch.setattr("app.routers.decisions.email_service.envoyer_email", mock)
    return mock


def _entete(utilisateur):
    return {"Authorization": f"Bearer {create_access_token(str(utilisateur.id))}"}


_SIGNATURE_FACTICE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


def _soumettre(client, tiers, objet, budget_engage):
    """POST multipart/form-data (le contrat est desormais une donnee cle
    obligatoire, section 3 du CDC fonctionnel - un fichier PDF factice
    minimal suffit pour ces tests, son contenu n'est jamais interprete."""
    return client.post(
        "/api/v1/achats/",
        data={"tiers": tiers, "objet": objet, "budget_engage": str(budget_engage)},
        files={"fichier_contrat": ("contrat.pdf", b"%PDF-1.4 contenu factice", "application/pdf")},
    )


async def test_soumission_bloquee_si_budget_insuffisant(client, db_session):
    from datetime import UTC, datetime

    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, "Fournisseur X", "Licences logicielles", 500)

    assert reponse.status_code == 422
    assert "budget" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_sans_service_juridique_actif_est_rejetee(client, db_session):
    from datetime import UTC, datetime

    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=10000)
    # Aucun compte SERVICE_JURIDIQUE cree.

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await _soumettre(client, "Fournisseur X", "Licences logicielles", 500)

    assert reponse.status_code == 422
    assert "juridique" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_circuit_complet_avis_juridique_puis_signature_dg_consomme_le_budget_une_fois(
    client, db_session
):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
    assert soumission.status_code == 201
    assert soumission.json()["statut_global"] == "en_cours"
    demande_id = soumission.json()["id"]
    etape1_id = soumission.json()["premiere_etape_id"]

    from app.services import decision_tokens
    from app.services.extensions import suivi_budgetaire

    # --- Niveau 1 : avis favorable du service juridique -> doit escalader. ---
    jeton_juriste = await decision_tokens.generer_jeton_decision(
        db_session, uuid.UUID(etape1_id), "approuver", juriste.id
    )
    await db_session.commit()
    decision1 = await client.post(
        f"/api/v1/decisions/{jeton_juriste}", json={}, headers=_entete(juriste)
    )
    assert decision1.status_code == 200
    assert decision1.json()["statut_global"] == "en_cours"

    solde_avant_dg = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", exercice)
    assert solde_avant_dg == 5000  # pas encore consomme : decision non definitive

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow

    resultat = await db_session.execute(
        select(EtapeWorkflow).where(
            EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
        )
    )
    etape2 = resultat.scalar_one()
    assert str(etape2.approbateur_attendu_id) == str(dg.id)
    from app.models.enums import RoleEtape

    assert etape2.role == RoleEtape.SIGNATAIRE

    # --- Niveau 2 : signature de la Direction generale -> termine, consomme le budget. ---
    jeton_dg = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "signer", dg.id)
    await db_session.commit()
    decision2 = await client.post(
        f"/api/v1/decisions/{jeton_dg}",
        json={"signature_image_base64": _SIGNATURE_FACTICE_BASE64},
        headers=_entete(dg),
    )
    assert decision2.status_code == 200
    assert decision2.json()["statut_global"] == "terminee"

    solde_apres = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", exercice)
    assert solde_apres == 5000 - 1200
    app.dependency_overrides.pop(get_current_user, None)


async def test_refus_par_le_service_juridique_termine_sans_escalade_ni_budget(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
    etape1_id = soumission.json()["premiere_etape_id"]

    from app.services import decision_tokens
    from app.services.extensions import suivi_budgetaire

    jeton_refus = await decision_tokens.generer_jeton_decision(
        db_session, uuid.UUID(etape1_id), "refuser", juriste.id
    )
    await db_session.commit()
    decision = await client.post(
        f"/api/v1/decisions/{jeton_refus}",
        json={"commentaire": "Contrat non conforme"},
        headers=_entete(juriste),
    )
    assert decision.status_code == 200
    assert decision.json()["statut_global"] == "refusee"

    solde = await suivi_budgetaire.calculer_solde_disponible(db_session, "Ventes", exercice)
    assert solde == 5000
    app.dependency_overrides.pop(get_current_user, None)


async def test_escalade_sans_direction_generale_active_renvoie_une_erreur_propre(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)
    # Aucun compte DIRECTION_GENERALE cree.

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
    etape1_id = soumission.json()["premiere_etape_id"]

    from app.services import decision_tokens

    jeton_juriste = await decision_tokens.generer_jeton_decision(
        db_session, uuid.UUID(etape1_id), "approuver", juriste.id
    )
    await db_session.commit()
    decision = await client.post(
        f"/api/v1/decisions/{jeton_juriste}", json={}, headers=_entete(juriste)
    )

    assert decision.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_contrat_depose_est_accessible_au_demandeur_et_telechargeable(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
    demande_id = soumission.json()["id"]

    telechargement = await client.get(f"/api/v1/achats/{demande_id}/piece-jointe")
    assert telechargement.status_code == 200
    assert telechargement.content == b"%PDF-1.4 contenu factice"
    app.dependency_overrides.pop(get_current_user, None)


async def test_contrat_inaccessible_a_un_employe_tiers_sans_role(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    autre_employe = await _creer_utilisateur(
        db_session, RoleUtilisateur.EMPLOYE, email="autre@example.com", service="Ventes"
    )
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
    demande_id = soumission.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: autre_employe
    reponse = await client.get(f"/api/v1/achats/{demande_id}/piece-jointe")
    assert reponse.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


async def test_soumission_refuse_un_type_de_fichier_non_accepte(client, db_session):
    from datetime import UTC, datetime

    await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/achats/",
        data={"tiers": "Fournisseur X", "objet": "Licences", "budget_engage": "1200"},
        files={"fichier_contrat": ("contrat.exe", b"binaire", "application/x-msdownload")},
    )

    assert reponse.status_code == 422
    app.dependency_overrides.pop(get_current_user, None)


async def test_bon_de_commande_indisponible_avant_finalisation(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
    demande_id = soumission.json()["id"]

    reponse = await client.get(f"/api/v1/achats/{demande_id}/bon-de-commande")
    assert reponse.status_code == 409
    app.dependency_overrides.pop(get_current_user, None)


async def test_bon_de_commande_genere_apres_signature_avec_numero_sequentiel(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=10000)

    from app.services import decision_tokens

    async def _finaliser_un_achat():
        app.dependency_overrides[get_current_user] = lambda: employe
        soumission = await _soumettre(client, "Fournisseur X", "Licences logicielles", 1200)
        demande_id = soumission.json()["id"]
        etape1_id = soumission.json()["premiere_etape_id"]

        jeton_juriste = await decision_tokens.generer_jeton_decision(
            db_session, uuid.UUID(etape1_id), "approuver", juriste.id
        )
        await db_session.commit()
        await client.post(f"/api/v1/decisions/{jeton_juriste}", json={}, headers=_entete(juriste))

        from sqlalchemy import select

        from app.models.etape_workflow import EtapeWorkflow

        resultat = await db_session.execute(
            select(EtapeWorkflow).where(
                EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
            )
        )
        etape2 = resultat.scalar_one()
        jeton_dg = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "signer", dg.id)
        await db_session.commit()
        await client.post(
            f"/api/v1/decisions/{jeton_dg}",
            json={"signature_image_base64": _SIGNATURE_FACTICE_BASE64},
            headers=_entete(dg),
        )
        return demande_id

    premiere_demande_id = await _finaliser_un_achat()
    seconde_demande_id = await _finaliser_un_achat()

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse1 = await client.get(f"/api/v1/achats/{premiere_demande_id}/bon-de-commande")
    reponse2 = await client.get(f"/api/v1/achats/{seconde_demande_id}/bon-de-commande")

    assert reponse1.status_code == 200
    assert reponse1.headers["content-type"] == "application/pdf"
    assert reponse1.headers["content-disposition"] == f'attachment; filename="BC-{exercice}-0001.pdf"'
    assert reponse2.headers["content-disposition"] == f'attachment; filename="BC-{exercice}-0002.pdf"'

    # Meme numero a un second telechargement (persiste, pas recalcule).
    reponse1_bis = await client.get(f"/api/v1/achats/{premiere_demande_id}/bon-de-commande")
    assert reponse1_bis.headers["content-disposition"] == reponse1.headers["content-disposition"]
    app.dependency_overrides.pop(get_current_user, None)


async def _escalader_jusqua_la_dg(client, db_session, juriste, employe, tiers="Fournisseur X", montant=1200):
    """Prepare une demande d'achat jusqu'a l'etape 2 (Direction generale), retourne son id."""
    from app.services import decision_tokens

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, tiers, "Licences logicielles", montant)
    demande_id = soumission.json()["id"]
    etape1_id = soumission.json()["premiere_etape_id"]

    jeton_juriste = await decision_tokens.generer_jeton_decision(
        db_session, uuid.UUID(etape1_id), "approuver", juriste.id
    )
    await db_session.commit()
    reponse = await client.post(f"/api/v1/decisions/{jeton_juriste}", json={}, headers=_entete(juriste))
    assert reponse.status_code == 200
    return demande_id


async def test_escalade_genere_un_jeton_signer_pas_approuver_pour_la_dg(client, db_session):
    """Verifie la garantie centrale : la Direction generale ne recoit jamais
    de jeton 'approuver' - seulement 'signer' ou 'refuser'."""
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    demande_id = await _escalader_jusqua_la_dg(client, db_session, juriste, employe)

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.models.jeton_decision import JetonDecision

    etape2 = (
        await db_session.execute(
            select(EtapeWorkflow).where(
                EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
            )
        )
    ).scalar_one()
    actions = {
        row.action_autorisee
        for row in (
            await db_session.execute(
                select(JetonDecision).where(JetonDecision.etape_workflow_id == etape2.id)
            )
        ).scalars()
    }
    assert actions == {"signer", "refuser"}
    app.dependency_overrides.pop(get_current_user, None)


async def test_signer_sans_image_est_rejete(client, db_session):
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    demande_id = await _escalader_jusqua_la_dg(client, db_session, juriste, employe)

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.services import decision_tokens

    etape2 = (
        await db_session.execute(
            select(EtapeWorkflow).where(
                EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
            )
        )
    ).scalar_one()
    jeton_dg = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "signer", dg.id)
    await db_session.commit()

    reponse = await client.post(f"/api/v1/decisions/{jeton_dg}", json={}, headers=_entete(dg))

    assert reponse.status_code == 422
    assert "signature" in reponse.json()["detail"].lower()
    app.dependency_overrides.pop(get_current_user, None)


async def test_un_jeton_approuver_force_pour_une_etape_signataire_est_rejete(client, db_session):
    """Defense en profondeur : meme si un jeton 'approuver' existait pour
    une etape Signataire (bug, jeton forge...), il doit etre rejete plutot
    que traite comme une decision valide."""
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    demande_id = await _escalader_jusqua_la_dg(client, db_session, juriste, employe)

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.services import decision_tokens

    etape2 = (
        await db_session.execute(
            select(EtapeWorkflow).where(
                EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
            )
        )
    ).scalar_one()
    jeton_force = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "approuver", dg.id)
    await db_session.commit()

    reponse = await client.post(f"/api/v1/decisions/{jeton_force}", json={}, headers=_entete(dg))

    assert reponse.status_code == 400
    app.dependency_overrides.pop(get_current_user, None)


async def test_signature_est_reellement_stockee_et_integree_au_bon_de_commande(client, db_session):
    import base64 as b64
    from datetime import UTC, datetime

    exercice = datetime.now(UTC).year
    juriste = await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _creer_utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    demande_id = await _escalader_jusqua_la_dg(client, db_session, juriste, employe)

    from sqlalchemy import select

    from app.models.etape_workflow import EtapeWorkflow
    from app.services import decision_tokens, stockage_fichiers

    etape2 = (
        await db_session.execute(
            select(EtapeWorkflow).where(
                EtapeWorkflow.demande_id == uuid.UUID(demande_id), EtapeWorkflow.niveau == 2
            )
        )
    ).scalar_one()
    jeton_dg = await decision_tokens.generer_jeton_decision(db_session, etape2.id, "signer", dg.id)
    await db_session.commit()

    reponse = await client.post(
        f"/api/v1/decisions/{jeton_dg}",
        json={"signature_image_base64": _SIGNATURE_FACTICE_BASE64},
        headers=_entete(dg),
    )
    assert reponse.status_code == 200

    await db_session.refresh(etape2)
    assert etape2.signature_cle_stockage is not None
    contenu_stocke = stockage_fichiers.lire_fichier(etape2.signature_cle_stockage)
    assert contenu_stocke == b64.b64decode(_SIGNATURE_FACTICE_BASE64)

    app.dependency_overrides[get_current_user] = lambda: employe
    bon_de_commande = await client.get(f"/api/v1/achats/{demande_id}/bon-de-commande")
    assert bon_de_commande.status_code == 200
    app.dependency_overrides.pop(get_current_user, None)


async def test_le_contrat_reste_telechargeable_meme_apres_une_piece_de_discussion(client, db_session):
    """La route du contrat renvoyait 'la piece la plus recente de la demande' :
    une piece deposee dans la discussion l'aurait remplacee."""
    from app.models.piece_jointe import PieceJointe
    from app.models.message_clarification import MessageClarification
    from datetime import UTC, datetime, timedelta

    exercice = datetime.now(UTC).year
    await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_enveloppe(db_session, "Ventes", exercice, budget_alloue=5000)

    app.dependency_overrides[get_current_user] = lambda: employe
    soumission = await _soumettre(client, "Fournisseur X", "Licences", 1200)
    demande_id = uuid.UUID(soumission.json()["id"])

    message = MessageClarification(demande_id=demande_id, auteur_id=employe.id, contenu="pièce")
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        PieceJointe(
            demande_id=demande_id, message_id=message.id, nom_original="autre.pdf", cle_stockage="inexistante.pdf",
            deposee_le=datetime.now(UTC) + timedelta(hours=1),  # plus recente que le contrat
        )
    )
    await db_session.commit()

    reponse = await client.get(f"/api/v1/achats/{demande_id}/piece-jointe")

    assert reponse.status_code == 200
    assert reponse.content == b"%PDF-1.4 contenu factice"
    app.dependency_overrides.pop(get_current_user, None)


async def test_contrat_jusqu_a_30_mo_au_dela_refuse(client, db_session):
    """Passee de 10 a 30 Mo (05/10) puis 40 Mo (07/10) : un contrat de 12 Mo passe (refuse avant), 40 Mo + 1 octet est refuse."""
    from datetime import UTC, datetime

    employe = await _creer_utilisateur(db_session, RoleUtilisateur.EMPLOYE, service="Ventes")
    await _creer_utilisateur(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _creer_enveloppe(db_session, "Ventes", datetime.now(UTC).year, budget_alloue=100000)
    app.dependency_overrides[get_current_user] = lambda: employe
    try:
        def envoi(octets):
            return client.post(
                "/api/v1/achats/",
                data={"tiers": "Fournisseur X", "objet": "Contrat volumineux", "budget_engage": "500"},
                files={"fichier_contrat": ("contrat.pdf", octets, "application/pdf")},
            )

        ok = await envoi(b"%PDF" + b"0" * (12 * 1024 * 1024))
        trop = await envoi(b"%PDF" + b"0" * (40 * 1024 * 1024 - 3))
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert ok.status_code == 201, ok.text
    assert trop.status_code == 422 and "40 Mo" in trop.json()["detail"]
