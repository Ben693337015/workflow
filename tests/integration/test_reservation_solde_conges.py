"""
Corrections R17 (reservation du solde), R18 (decision atomique), R20 (duree) et R4 (jours entiers).

Cycle de vie verifie ici : soumission (reservation) -> refus / annulation / modification (liberation)
ou approbation (confirmation), avec, a chaque etape, l'egalite fondamentale du CDC 11.1 :
    solde disponible == somme des mouvements de `mouvements_conges`.
"""
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.main import app
from app.models.demande import Demande
from app.models.enums import MotifMouvementConges, RoleUtilisateur, StatutDemande, StatutEtape
from app.models.etape_workflow import EtapeWorkflow
from app.models.mouvement_conges import MouvementConges
from app.models.solde_conges import SoldeConges
from app.models.user import Utilisateur
from app.services import decision_tokens
from app.services.extensions import verrou_rh
from tests.integration.test_conges_api import _preparer_employe_et_manager


@pytest.fixture(autouse=True)
def _mock_envoi_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.routers.conges.email_service.envoyer_email", mock)
    return mock


def _entete(utilisateur):
    return {"Authorization": f"Bearer {create_access_token(str(utilisateur.id))}"}


async def _solde(db_session, employe_id, type_conge_id) -> SoldeConges:
    resultat = await db_session.execute(
        select(SoldeConges)
        .where(SoldeConges.utilisateur_id == employe_id, SoldeConges.type_conge_id == type_conge_id)
        .execution_options(populate_existing=True)
    )
    return resultat.scalar_one()


async def _somme_mouvements(db_session, employe_id) -> float:
    resultat = await db_session.execute(
        select(func.coalesce(func.sum(MouvementConges.delta), 0)).where(MouvementConges.utilisateur_id == employe_id)
    )
    return float(resultat.scalar_one())


async def _preparer(db_session, solde_jours: float):
    """Comme _preparer_employe_et_manager, avec le mouvement `solde_initial` qu'ecrit la route DRH
    (sans lui, l'egalite solde == somme des mouvements ne peut pas tenir dans un jeu de test)."""
    employe, manager, type_conge = await _preparer_employe_et_manager(db_session, solde_jours=solde_jours)
    if solde_jours:
        db_session.add(
            MouvementConges(
                utilisateur_id=employe.id, type_conge_id=type_conge.id, exercice=2026, demande_id=None,
                delta=solde_jours, motif=MotifMouvementConges.SOLDE_INITIAL,
            )
        )
        await db_session.commit()
    return employe, manager, type_conge


async def _soumettre(client, employe, type_conge, debut="2026-06-01", fin="2026-06-03"):
    app.dependency_overrides[get_current_user] = lambda: employe
    reponse = await client.post(
        "/api/v1/conges/",
        json={"type_conge_id": str(type_conge.id), "date_debut": debut, "date_fin": fin},
    )
    app.dependency_overrides.pop(get_current_user, None)
    return reponse


async def _decider(client, db_session, manager, reponse_soumission, action="approuver", commentaire=None):
    etape_id = uuid.UUID(reponse_soumission.json()["premiere_etape_id"])
    jeton = await decision_tokens.generer_jeton_decision(db_session, etape_id, action, manager.id)
    await db_session.commit()
    corps = {"commentaire": commentaire} if commentaire else {}
    return await client.post(f"/api/v1/decisions/{jeton}", json=corps, headers=_entete(manager))


# ---------------------------------------------------------------- R17 : reservation a la soumission


async def test_la_soumission_reserve_le_solde_et_ecrit_un_mouvement(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)

    reponse = await _soumettre(client, employe, type_conge)

    assert reponse.status_code == 201
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 2  # 5 - 3 : deja retire du disponible
    assert float(solde.jours_reserves) == 3
    assert float(solde.jours_pris) == 0
    mouvements = (
        await db_session.execute(select(MouvementConges).where(MouvementConges.demande_id.is_not(None)))
    ).scalars().all()
    assert len(mouvements) == 1
    assert float(mouvements[0].delta) == -3
    assert mouvements[0].motif == MotifMouvementConges.RESERVATION
    assert str(mouvements[0].demande_id) == reponse.json()["id"]
    assert await _somme_mouvements(db_session, employe.id) == float(solde.solde_jours)  # 5 - 3 = 2


async def test_deux_demandes_rapprochees_ne_peuvent_pas_depasser_le_solde(client, db_session):
    """Le defaut R17 : sans reservation, les deux demandes passaient le controle contre le meme solde intact."""
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)

    premiere = await _soumettre(client, employe, type_conge, "2026-06-01", "2026-06-03")  # 3 jours
    seconde = await _soumettre(client, employe, type_conge, "2026-07-01", "2026-07-03")  # 3 jours de plus

    assert premiere.status_code == 201
    assert seconde.status_code == 422
    assert "insuffisant" in seconde.json()["detail"].lower()
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 2  # seule la premiere reservation existe
    assert float(solde.jours_reserves) == 3
    nb_demandes = (await db_session.execute(select(func.count()).select_from(Demande))).scalar_one()
    assert nb_demandes == 1  # la seconde n'a rien laisse derriere elle


async def test_la_demande_refusee_pour_solde_insuffisant_ne_laisse_aucune_trace(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=2)

    reponse = await _soumettre(client, employe, type_conge)  # 3 jours pour 2 disponibles

    assert reponse.status_code == 422
    assert (
        await db_session.execute(
            select(func.count()).select_from(MouvementConges).where(MouvementConges.demande_id.is_not(None))
        )
    ).scalar_one() == 0
    assert float((await _solde(db_session, employe.id, type_conge.id)).solde_jours) == 2


async def test_approbation_confirme_la_reservation_sans_deuxieme_debit(client, db_session):
    employe, manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge)

    decision = await _decider(client, db_session, manager, soumission, "approuver")

    assert decision.status_code == 200
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 2  # pas debite une seconde fois
    assert float(solde.jours_reserves) == 0
    assert float(solde.jours_pris) == 3
    assert await _somme_mouvements(db_session, employe.id) == float(solde.solde_jours)


async def test_refus_rend_les_jours_reserves(client, db_session):
    employe, manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge)

    decision = await _decider(client, db_session, manager, soumission, "refuser", commentaire="Période chargée")

    assert decision.status_code == 200
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 5
    assert float(solde.jours_reserves) == 0
    assert float(solde.jours_pris) == 0
    motifs = [m.motif for m in (await db_session.execute(select(MouvementConges))).scalars().all()]
    assert MotifMouvementConges.LIBERATION_REFUS in motifs
    assert await _somme_mouvements(db_session, employe.id) == 5


async def test_annulation_rend_les_jours_reserves(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge)
    demande_id = soumission.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: employe
    annulation = await client.post(f"/api/v1/conges/{demande_id}/annuler")
    app.dependency_overrides.pop(get_current_user, None)

    assert annulation.status_code == 200
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 5
    assert float(solde.jours_reserves) == 0
    motifs = [m.motif for m in (await db_session.execute(select(MouvementConges))).scalars().all()]
    assert MotifMouvementConges.LIBERATION_ANNULATION in motifs
    assert await _somme_mouvements(db_session, employe.id) == 5


async def test_annuler_deux_fois_ne_rend_pas_les_jours_deux_fois(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge)
    demande_id = soumission.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: employe
    premiere = await client.post(f"/api/v1/conges/{demande_id}/annuler")
    seconde = await client.post(f"/api/v1/conges/{demande_id}/annuler")
    app.dependency_overrides.pop(get_current_user, None)

    assert premiere.status_code == 200
    assert seconde.status_code == 409
    assert float((await _solde(db_session, employe.id, type_conge.id)).solde_jours) == 5


async def test_modification_reduit_la_reservation(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge, "2026-06-01", "2026-06-03")  # 3 jours
    demande_id = soumission.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: employe
    modification = await client.patch(f"/api/v1/conges/{demande_id}", json={"date_fin": "2026-06-02"})  # 2 jours
    app.dependency_overrides.pop(get_current_user, None)

    assert modification.status_code == 200
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 3
    assert float(solde.jours_reserves) == 2
    assert await _somme_mouvements(db_session, employe.id) == 3


async def test_modification_impossible_conserve_lancienne_reservation(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge, "2026-06-01", "2026-06-03")  # 3 jours
    demande_id = soumission.json()["id"]
    employe_id, type_conge_id = employe.id, type_conge.id  # captures : le rollback de la route expire les objets

    app.dependency_overrides[get_current_user] = lambda: employe
    modification = await client.patch(f"/api/v1/conges/{demande_id}", json={"date_fin": "2026-06-20"})  # 20 jours
    app.dependency_overrides.pop(get_current_user, None)

    assert modification.status_code == 422
    solde = await _solde(db_session, employe_id, type_conge_id)
    assert float(solde.solde_jours) == 2  # l'ancienne reservation de 3 jours est intacte
    assert float(solde.jours_reserves) == 3
    demande = await db_session.get(Demande, uuid.UUID(demande_id))
    await db_session.refresh(demande)
    assert demande.donnees["date_fin"] == "2026-06-03"


async def test_modification_ne_compte_pas_deux_fois_la_meme_demande(client, db_session):
    """Etendre une demande de 3 a 5 jours avec 5 jours de solde doit reussir : les 3 jours deja reserves
    par cette demande ne doivent pas etre comptes contre elle-meme."""
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge, "2026-06-01", "2026-06-03")
    demande_id = soumission.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: employe
    modification = await client.patch(f"/api/v1/conges/{demande_id}", json={"date_fin": "2026-06-05"})
    app.dependency_overrides.pop(get_current_user, None)

    assert modification.status_code == 200
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 0
    assert float(solde.jours_reserves) == 5


async def test_regularisation_approuvee_debite_le_solde_avec_mouvement(client, db_session):
    employe, manager, type_conge = await _preparer(db_session, solde_jours=5)
    app.dependency_overrides[get_current_user] = lambda: manager

    reponse = await client.post(
        "/api/v1/conges/regularisation",
        json={
            "employe_id": str(employe.id), "type_conge_id": str(type_conge.id),
            "date_debut": "2026-06-01", "date_fin": "2026-06-02", "action": "approuver",
        },
    )
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 201
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 3
    assert float(solde.jours_pris) == 2
    assert float(solde.jours_reserves) == 0
    assert await _somme_mouvements(db_session, employe.id) == 3


async def test_demande_anterieure_a_la_correction_est_consommee_directement(client, db_session):
    """Compatibilite : une demande en cours creee AVANT R17 n'a aucun mouvement de reservation."""
    employe, manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge)
    demande_id = uuid.UUID(soumission.json()["id"])

    # On revient a l'etat d'avant la correction : pas de reservation, solde disponible intact.
    solde = await _solde(db_session, employe.id, type_conge.id)
    solde.solde_jours = 5
    solde.jours_reserves = 0
    for mouvement in (await db_session.execute(select(MouvementConges))).scalars().all():
        await db_session.delete(mouvement)  # ni solde initial ni reservation : etat d'avant la correction
    await db_session.commit()

    decision = await _decider(client, db_session, manager, soumission, "approuver")

    assert decision.status_code == 200
    solde = await _solde(db_session, employe.id, type_conge.id)
    assert float(solde.solde_jours) == 2  # consommee directement, comme avant
    assert float(solde.jours_pris) == 3
    mouvements = (await db_session.execute(select(MouvementConges))).scalars().all()
    assert [float(m.delta) for m in mouvements] == [-3]
    assert mouvements[0].demande_id == demande_id


# ---------------------------------------------------------------- R18 : decision atomique


async def test_echec_du_debit_annule_toute_la_decision(client, db_session, monkeypatch):
    """R18 : si le debit echoue, la decision NE DOIT PAS etre enregistree (avant : elle l'etait deja)."""
    employe, manager, type_conge = await _preparer(db_session, solde_jours=5)
    soumission = await _soumettre(client, employe, type_conge)
    etape_id = uuid.UUID(soumission.json()["premiere_etape_id"])
    demande_id = uuid.UUID(soumission.json()["id"])
    employe_id, type_conge_id = employe.id, type_conge.id  # capturés : les objets expirent au rollback

    async def _echec(*_args, **_kwargs):
        raise RuntimeError("incident pendant le debit")

    monkeypatch.setattr(verrou_rh, "confirmer_reservation", _echec)

    with pytest.raises(RuntimeError):
        await _decider(client, db_session, manager, soumission, "approuver")
    await db_session.rollback()  # la session de la requete est abandonnee, comme en production

    etape = await db_session.get(EtapeWorkflow, etape_id)
    await db_session.refresh(etape)
    demande = await db_session.get(Demande, demande_id)
    await db_session.refresh(demande)
    assert etape.statut == StatutEtape.EN_ATTENTE
    assert demande.statut_global == StatutDemande.EN_COURS
    solde = await _solde(db_session, employe_id, type_conge_id)
    assert float(solde.jours_pris) == 0  # rien n'a ete consomme
    assert float(solde.jours_reserves) == 3  # la reservation de la soumission est intacte


# ---------------------------------------------------------------- R20 : duree


async def test_duree_par_defaut_en_jours_calendaires(db_session):
    from datetime import date

    # Lundi 1er juin 2026 -> dimanche 7 juin 2026
    assert await verrou_rh.calculer_duree_deductible(db_session, date(2026, 6, 1), date(2026, 6, 7)) == 7


async def test_duree_hors_week_ends_quand_le_reglage_est_active(db_session, monkeypatch):
    from datetime import date

    monkeypatch.setattr(get_settings(), "conges_exclure_weekends", True)

    assert await verrou_rh.calculer_duree_deductible(db_session, date(2026, 6, 1), date(2026, 6, 7)) == 5


async def test_ferie_un_week_end_nest_pas_retranche_deux_fois(db_session, monkeypatch):
    from datetime import date

    from app.models.jour_ferie import JourFerie

    monkeypatch.setattr(get_settings(), "conges_exclure_weekends", True)
    db_session.add(JourFerie(nom="Ferie un samedi", date=date(2026, 6, 6), recurrent=False))  # samedi
    db_session.add(JourFerie(nom="Ferie un mercredi", date=date(2026, 6, 3), recurrent=False))
    await db_session.commit()

    # 5 jours ouvres (lun-ven) - 1 (mercredi ferie) ; le samedi ferie est deja exclu comme week-end.
    assert await verrou_rh.calculer_duree_deductible(db_session, date(2026, 6, 1), date(2026, 6, 7)) == 4


# ---------------------------------------------------------------- R4 + mouvements RH


async def _drh(db_session):
    drh = Utilisateur(
        email="drh@example.com", mot_de_passe_hash="hash", nom_complet="DRH", service="RH", role=RoleUtilisateur.DRH
    )
    db_session.add(drh)
    await db_session.commit()
    return drh


async def test_la_drh_definit_un_solde_avec_un_mouvement_initial_puis_un_ajustement(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=0)
    drh = await _drh(db_session)
    app.dependency_overrides[get_current_user] = lambda: drh
    corps = {"type_conge_id": str(type_conge.id), "exercice": 2027}

    creation = await client.put(f"/api/v1/utilisateurs/{employe.id}/soldes-conges", json={**corps, "jours_acquis": 25})
    ajustement = await client.put(f"/api/v1/utilisateurs/{employe.id}/soldes-conges", json={**corps, "jours_acquis": 27})
    app.dependency_overrides.pop(get_current_user, None)

    assert creation.status_code == 200 and ajustement.status_code == 200
    mouvements = (
        await db_session.execute(select(MouvementConges).where(MouvementConges.exercice == 2027))
    ).scalars().all()
    par_motif = {m.motif: float(m.delta) for m in mouvements}
    assert par_motif == {MotifMouvementConges.SOLDE_INITIAL: 25, MotifMouvementConges.AJUSTEMENT_MANUEL: 2}


async def test_un_solde_en_demi_journee_est_refuse(client, db_session):
    employe, _manager, type_conge = await _preparer(db_session, solde_jours=0)
    drh = await _drh(db_session)
    app.dependency_overrides[get_current_user] = lambda: drh

    reponse = await client.put(
        f"/api/v1/utilisateurs/{employe.id}/soldes-conges",
        json={"type_conge_id": str(type_conge.id), "exercice": 2027, "jours_acquis": 12.5},
    )
    app.dependency_overrides.pop(get_current_user, None)

    assert reponse.status_code == 422
    assert "entier" in str(reponse.json()).lower()
