"""
Tests unitaires - verrou RH sur les congés (extension native n2, section 11).

Couvre aussi les écarts intégrés suite à la revue comparative : exclusion
des jours fériés, solde par type de congé, consommation réelle du solde.
"""
from datetime import date

from app.models.enums import RoleUtilisateur
from app.models.jour_ferie import JourFerie
from app.models.solde_conges import SoldeConges
from app.models.type_conge import TypeConge
from app.models.user import Utilisateur
from app.services.extensions.verrou_rh import (
    calculer_duree_deductible,
    calculer_duree_en_jours,
    consommer_solde,
    obtenir_solde,
    solde_suffisant,
)


async def _creer_type_conge(db_session, code="conge_paye"):
    type_conge = TypeConge(code=code, nom="Congé payé", taux_acquisition_jours_mois=2.5)
    db_session.add(type_conge)
    await db_session.flush()
    return type_conge


async def _creer_utilisateur_avec_solde(db_session, jours_disponibles: float, exercice: int = 2026, type_conge=None):
    utilisateur = Utilisateur(
        email="employe@example.com",
        mot_de_passe_hash="hash-non-verifie-dans-ce-test",
        nom_complet="Employe Test",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    await db_session.flush()

    if type_conge is None:
        type_conge = await _creer_type_conge(db_session)

    db_session.add(
        SoldeConges(
            utilisateur_id=utilisateur.id,
            type_conge_id=type_conge.id,
            solde_jours=jours_disponibles,
            jours_acquis=jours_disponibles,
            jours_pris=0,
            exercice=exercice,
        )
    )
    await db_session.commit()
    return utilisateur, type_conge


def test_calculer_duree_en_jours_est_inclusive_aux_deux_bornes():
    duree = calculer_duree_en_jours(date(2026, 3, 2), date(2026, 3, 4))
    assert duree == 3  # 2, 3 et 4 mars


def test_calculer_duree_en_jours_pour_une_seule_journee():
    assert calculer_duree_en_jours(date(2026, 3, 2), date(2026, 3, 2)) == 1


async def test_solde_suffisant_autorise_la_demande(db_session):
    utilisateur, type_conge = await _creer_utilisateur_avec_solde(db_session, jours_disponibles=10)

    ok, nombre_jours, solde_disponible = await solde_suffisant(
        db_session, utilisateur, type_conge.id, date(2026, 6, 1), date(2026, 6, 3)
    )

    assert ok is True
    assert nombre_jours == 3
    assert solde_disponible == 10


async def test_solde_insuffisant_bloque_la_demande(db_session):
    utilisateur, type_conge = await _creer_utilisateur_avec_solde(db_session, jours_disponibles=2)

    ok, nombre_jours, solde_disponible = await solde_suffisant(
        db_session, utilisateur, type_conge.id, date(2026, 6, 1), date(2026, 6, 5)
    )

    assert ok is False
    assert nombre_jours == 5
    assert solde_disponible == 2


async def test_solde_exactement_egal_a_la_duree_est_accepte(db_session):
    utilisateur, type_conge = await _creer_utilisateur_avec_solde(db_session, jours_disponibles=3)

    ok, nombre_jours, _ = await solde_suffisant(
        db_session, utilisateur, type_conge.id, date(2026, 6, 1), date(2026, 6, 3)
    )

    assert ok is True
    assert nombre_jours == 3


async def test_absence_de_ligne_de_solde_bloque_la_demande(db_session):
    """Aucune ligne soldes_conges pour ce type/exercice -> traité comme un solde de 0 jour."""
    utilisateur = Utilisateur(
        email="nouvel-employe@example.com",
        mot_de_passe_hash="hash-non-verifie-dans-ce-test",
        nom_complet="Nouvel Employe",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    type_conge = await _creer_type_conge(db_session)
    await db_session.commit()

    ok, nombre_jours, solde_disponible = await solde_suffisant(
        db_session, utilisateur, type_conge.id, date(2026, 6, 1), date(2026, 6, 1)
    )

    assert ok is False
    assert solde_disponible == 0
    assert nombre_jours == 1


# --- Écart intégré : jours fériés déductibles -----------------------------

async def test_un_jour_ferie_non_recurrent_dans_la_periode_reduit_la_duree_deductible(db_session):
    db_session.add(JourFerie(nom="Fête nationale", date=date(2026, 6, 2), recurrent=False))
    await db_session.commit()

    duree = await calculer_duree_deductible(db_session, date(2026, 6, 1), date(2026, 6, 5))

    assert duree == 4  # 5 jours calendaires - 1 jour férié


async def test_un_jour_ferie_recurrent_est_detecte_quelle_que_soit_lannee(db_session):
    # Enregistré une autre année, mais récurrent -> doit compter en 2026 aussi.
    db_session.add(JourFerie(nom="1er mai", date=date(2019, 5, 1), recurrent=True))
    await db_session.commit()

    duree = await calculer_duree_deductible(db_session, date(2026, 4, 29), date(2026, 5, 2))

    assert duree == 3  # 4 jours calendaires - le 1er mai


async def test_solde_suffisant_utilise_la_duree_deductible_jours_feries_exclus(db_session):
    db_session.add(JourFerie(nom="Jour férié", date=date(2026, 6, 2), recurrent=False))
    utilisateur, type_conge = await _creer_utilisateur_avec_solde(db_session, jours_disponibles=4)

    # 5 jours calendaires demandés, mais 1 est férié -> 4 jours déductibles,
    # exactement couverts par le solde.
    ok, nombre_jours, _ = await solde_suffisant(
        db_session, utilisateur, type_conge.id, date(2026, 6, 1), date(2026, 6, 5)
    )

    assert ok is True
    assert nombre_jours == 4


# --- Écart intégré : consommation réelle du solde --------------------------

async def test_consommer_solde_decrement_le_disponible_et_incremente_les_pris(db_session):
    utilisateur, type_conge = await _creer_utilisateur_avec_solde(db_session, jours_disponibles=10)

    await consommer_solde(db_session, utilisateur.id, type_conge.id, 2026, 3)
    await db_session.commit()

    solde = await obtenir_solde(db_session, utilisateur.id, type_conge.id, 2026)
    assert float(solde.solde_jours) == 7
    assert float(solde.jours_pris) == 3


async def test_consommer_solde_sans_ligne_existante_ne_leve_pas_derreur(db_session):
    utilisateur = Utilisateur(
        email="sans-solde@example.com",
        mot_de_passe_hash="hash",
        nom_complet="Sans Solde",
        service="Support",
        role=RoleUtilisateur.EMPLOYE,
    )
    db_session.add(utilisateur)
    type_conge = await _creer_type_conge(db_session)
    await db_session.commit()

    await consommer_solde(db_session, utilisateur.id, type_conge.id, 2026, 3)  # ne doit pas planter
