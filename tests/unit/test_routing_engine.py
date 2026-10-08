"""Tests unitaires - moteur de routage (section 7)."""
import uuid

import pytest

from app.models.demande import Demande
from app.models.enums import RoleEtape, RoleUtilisateur, TypeProcessus
from app.models.user import Utilisateur
from app.services import routing_engine


async def test_premiere_etape_conges_cible_le_manager_direct(db_session):
    manager = Utilisateur(
        email="manager@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Manager Test",
        service="Support",
        role=RoleUtilisateur.MANAGER,
    )
    db_session.add(manager)
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

    demande = Demande(
        processus=TypeProcessus.CONGES,
        demandeur_id=employe.id,
        donnees={"type_absence": "Congé payé"},
    )

    etape = await routing_engine.determiner_premiere_etape(db_session, demande, employe)

    assert etape.niveau == 1
    assert etape.role == RoleEtape.APPROBATEUR
    assert etape.approbateur_attendu_id == manager.id


async def test_premiere_etape_conges_sans_manager_leve_une_erreur(db_session):
    employe = Utilisateur(
        id=uuid.uuid4(),
        email="sans-manager@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Sans Manager",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
        manager_id=None,
    )
    demande = Demande(processus=TypeProcessus.CONGES, demandeur_id=employe.id, donnees={})

    with pytest.raises(ValueError, match="manager"):
        await routing_engine.determiner_premiere_etape(db_session, demande, employe)


async def test_notes_frais_sous_le_seuil_ne_route_pas_vers_direction_financiere(db_session):
    """Ecart corrige (27/09) : verifie determiner_etape_suivante isolement,
    en complement des tests d'integration bout en bout (decisions/notes de
    frais)."""
    demande = Demande(
        processus=TypeProcessus.NOTES_FRAIS,
        demandeur_id=uuid.uuid4(),
        donnees={"montant": 100},
    )
    etape1 = type("EtapeFactice", (), {"niveau": 1, "est_derogation": False})()

    suivante = await routing_engine.determiner_etape_suivante(db_session, demande, etape1)

    assert suivante is None


async def test_notes_frais_au_dela_du_seuil_route_vers_direction_financiere_active(db_session):
    df = Utilisateur(
        email="df@example.com",
        mot_de_passe_hash="hash",
        nom_complet="DF Test",
        service="Finance",
        role=RoleUtilisateur.DIRECTION_FINANCIERE,
    )
    db_session.add(df)
    await db_session.flush()

    demande = Demande(
        processus=TypeProcessus.NOTES_FRAIS,
        demandeur_id=uuid.uuid4(),
        donnees={"montant": 800},
    )
    etape1 = type("EtapeFactice", (), {"niveau": 1, "est_derogation": False})()

    suivante = await routing_engine.determiner_etape_suivante(db_session, demande, etape1)

    assert suivante is not None
    assert suivante.niveau == 2
    assert suivante.role == RoleEtape.APPROBATEUR
    assert suivante.approbateur_attendu_id == df.id


async def test_achats_premiere_etape_cible_le_service_juridique_sans_manager(db_session):
    """Ecart notable par rapport aux conges/notes de frais : aucun manager
    n'intervient dans le routage des achats (CDC section 3)."""
    juriste = Utilisateur(
        email="juriste@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Juriste Test",
        service="Juridique",
        role=RoleUtilisateur.SERVICE_JURIDIQUE,
    )
    db_session.add(juriste)
    await db_session.flush()

    demandeur = Utilisateur(
        email="demandeur-achat@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Demandeur Test",
        service="Ventes",
        role=RoleUtilisateur.EMPLOYE,
        manager_id=None,  # aucun manager : ne doit pas bloquer le routage achats
    )
    db_session.add(demandeur)
    await db_session.flush()

    demande = Demande(
        processus=TypeProcessus.ACHATS,
        demandeur_id=demandeur.id,
        donnees={"tiers": "Fournisseur X", "objet": "Licences", "budget_engage": 2000},
    )

    etape = await routing_engine.determiner_premiere_etape(db_session, demande, demandeur)

    assert etape.niveau == 1
    assert etape.role == RoleEtape.APPROBATEUR
    assert etape.approbateur_attendu_id == juriste.id


async def test_achats_apres_avis_juridique_route_toujours_vers_la_direction_generale(db_session):
    """Contrairement aux notes de frais, le second niveau des achats n'est
    pas conditionnel : il a toujours lieu, role Signataire (section 8)."""
    dg = Utilisateur(
        email="dg@example.com",
        mot_de_passe_hash="hash",
        nom_complet="DG Test",
        service="Direction",
        role=RoleUtilisateur.DIRECTION_GENERALE,
    )
    db_session.add(dg)
    await db_session.flush()

    demande = Demande(
        processus=TypeProcessus.ACHATS,
        demandeur_id=uuid.uuid4(),
        donnees={"tiers": "Fournisseur X", "objet": "Licences", "budget_engage": 2000},
    )
    etape1 = type("EtapeFactice", (), {"niveau": 1, "est_derogation": False})()

    suivante = await routing_engine.determiner_etape_suivante(db_session, demande, etape1)

    assert suivante is not None
    assert suivante.niveau == 2
    assert suivante.role == RoleEtape.SIGNATAIRE
    assert suivante.approbateur_attendu_id == dg.id


async def test_achats_apres_direction_generale_termine_le_circuit(db_session):
    demande = Demande(processus=TypeProcessus.ACHATS, demandeur_id=uuid.uuid4(), donnees={})
    etape2 = type("EtapeFactice", (), {"niveau": 2, "est_derogation": False})()

    suivante = await routing_engine.determiner_etape_suivante(db_session, demande, etape2)

    assert suivante is None
