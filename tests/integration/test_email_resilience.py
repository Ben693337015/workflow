"""
Test d'intégration - résilience réelle de la notification par e-mail
(section 13.4 : une notification en échec ne doit jamais faire échouer la
transaction principale).

Contrairement aux autres tests, qui simulent l'envoi d'e-mail en remplaçant
directement `email_service.envoyer_email` (notre propre wrapper), celui-ci
simule une panne au niveau du SDK Resend lui-même (`resend.Emails.send`) -
le point d'échec réel en production (clé API absente/invalide, panne
réseau, domaine non vérifié...). Ça exerce réellement `asyncio.to_thread`
et la remontée d'exception jusqu'au `try/except` de l'appelant, plutôt que
de le contourner.
"""
from unittest.mock import MagicMock

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.enums import RoleUtilisateur
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.services import decision_tokens


@pytest.fixture
def _resend_en_panne(monkeypatch):
    """Simule une vraie panne du SDK Resend (clé invalide, réseau, etc.)."""
    appel_simule = MagicMock(side_effect=Exception("Resend indisponible (simulation de test)"))
    monkeypatch.setattr("resend.Emails.send", appel_simule)
    return appel_simule


async def test_soumission_conges_reussit_malgre_une_panne_resend_reelle(
    client, db_session, _resend_en_panne
):
    manager = Utilisateur(
        email="manager@example.com", mot_de_passe_hash="hash",
        nom_complet="Manager Test", service="Support", role=RoleUtilisateur.MANAGER,
    )
    db_session.add(manager)
    await db_session.flush()
    employe = Utilisateur(
        email="employe@example.com", mot_de_passe_hash="hash",
        nom_complet="Employe Test", service="Support", role=RoleUtilisateur.EMPLOYE,
        manager_id=manager.id,
    )
    db_session.add(employe)
    await db_session.flush()
    type_conge = TypeConge(code="conge_paye", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.flush()
    db_session.add(SoldeConges(
        utilisateur_id=employe.id, type_conge_id=type_conge.id,
        solde_jours=10, jours_acquis=10, jours_pris=0, exercice=2026,
    ))
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
    )

    # La demande doit malgre tout etre creee : l'echec Resend ne doit
    # jamais remonter jusqu'a la reponse HTTP (section 13.4).
    assert reponse.status_code == 201
    assert reponse.json()["statut_global"] == "en_cours"
    # Preuve que l'appel Resend a bien ete tente (et a bien echoue) plutot
    # que d'avoir ete court-circuite ailleurs dans le code.
    _resend_en_panne.assert_called_once()
    app.dependency_overrides.pop(get_current_user, None)


async def test_decision_reussit_malgre_une_panne_resend_reelle(client, db_session, _resend_en_panne):
    from app.models.demande import Demande
    from app.models.enums import RoleEtape, StatutDemande
    from app.models.etape_workflow import EtapeWorkflow
    from app.models.enums import TypeProcessus

    manager = Utilisateur(
        email="manager2@example.com", mot_de_passe_hash="hash",
        nom_complet="Manager Test", service="Support", role=RoleUtilisateur.MANAGER,
    )
    db_session.add(manager)
    await db_session.flush()
    employe = Utilisateur(
        email="employe2@example.com", mot_de_passe_hash="hash",
        nom_complet="Employe Test", service="Support", role=RoleUtilisateur.EMPLOYE,
        manager_id=manager.id,
    )
    db_session.add(employe)
    await db_session.flush()
    type_conge = TypeConge(code="conge_paye2", nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.flush()
    db_session.add(SoldeConges(
        utilisateur_id=employe.id, type_conge_id=type_conge.id,
        solde_jours=10, jours_acquis=10, jours_pris=0, exercice=2026,
    ))
    demande = Demande(
        processus=TypeProcessus.CONGES, demandeur_id=employe.id, initiee_par_id=employe.id,
        donnees={"type_conge_id": str(type_conge.id), "date_debut": "2026-06-01", "date_fin": "2026-06-03"},
        statut_global=StatutDemande.EN_COURS,
    )
    db_session.add(demande)
    await db_session.flush()
    etape = EtapeWorkflow(
        demande_id=demande.id, niveau=1, role=RoleEtape.APPROBATEUR,
        approbateur_attendu_id=manager.id,
    )
    db_session.add(etape)
    drh = Utilisateur(
        email="drh@example.com", mot_de_passe_hash="hash",
        nom_complet="DRH Test", service="RH", role=RoleUtilisateur.DRH,
    )
    db_session.add(drh)
    await db_session.commit()
    await db_session.refresh(etape)

    from app.core.security import create_access_token

    jeton = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", etape.approbateur_attendu_id)
    reponse = await client.post(
        f"/api/v1/decisions/{jeton}",
        json={},
        headers={"Authorization": f"Bearer {create_access_token(str(manager.id))}"},
    )

    assert reponse.status_code == 200
    assert reponse.json()["statut_global"] == "terminee"
    # La decision a bien tente de notifier la DRH ET le demandeur (ecart
    # corrige du 15/09), et a echoue silencieusement sur les deux (best-effort).
    assert _resend_en_panne.call_count == 2
