"""
Rappels automatiques (CDC fonctionnel 2.4) : relance des decisions en attente
selon une frequence parametrable, sans doublon, sans jamais perdre un lien valide.
"""
import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.demande import Demande
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleEtape, RoleUtilisateur, StatutDemande, StatutEtape, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.user import Utilisateur
from app.services import decision_tokens, planificateur, rappels
from app.services.rappels import settings as settings_rappels

NOTE = {"montant": 50, "categorie": "Repas", "date_depense": "2026-03-01", "description": "x"}


async def _utilisateur(db, role, service="Ventes", actif=True):
    u = Utilisateur(
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@example.com", mot_de_passe_hash="hash",
        nom_complet=f"Test {role.value}", service=service, role=role, actif=actif,
    )
    db.add(u)
    await db.commit()
    return u


async def _etape(db, approbateur, demandeur, processus=TypeProcessus.NOTES_FRAIS, donnees=None,
                 role=RoleEtape.APPROBATEUR, heures=50, statut=StatutEtape.EN_ATTENTE,
                 statut_demande=StatutDemande.EN_COURS, derogation=False):
    demande = Demande(processus=processus, demandeur_id=demandeur.id, initiee_par_id=demandeur.id,
                      donnees=donnees or NOTE, statut_global=statut_demande)
    db.add(demande)
    await db.flush()
    etape = EtapeWorkflow(demande_id=demande.id, niveau=1, role=role, approbateur_attendu_id=approbateur.id,
                          statut=statut, est_derogation=derogation, cree_le=datetime.now(UTC) - timedelta(hours=heures))
    db.add(etape)
    await db.commit()
    return demande, etape


@pytest.fixture
def emails(monkeypatch):
    # Un seul simulacre : rappels.py et decisions.py referencent le MEME module
    # email_service, donc patcher les deux chemins reviendrait a s'ecraser soi-meme.
    mock = AsyncMock()
    monkeypatch.setattr("app.services.email_service.envoyer_email", mock)
    return mock


@pytest.fixture
async def acteurs(db_session):
    manager = await _utilisateur(db_session, RoleUtilisateur.MANAGER)
    employe = await _utilisateur(db_session, RoleUtilisateur.EMPLOYE)
    return manager, employe


def _jeton_du_mail(mock, indice=-1):
    corps = mock.call_args_list[indice].kwargs["corps_html"]
    return re.findall(r"/decisions/([A-Za-z0-9_\-]+)'", corps)


# --- declenchement -------------------------------------------------------------------

async def test_un_rappel_est_envoye_apres_48h_d_attente_et_consigne_au_journal(db_session, acteurs, emails):
    manager, employe = acteurs
    _, etape = await _etape(db_session, manager, employe, heures=50)

    envoyes = await rappels.traiter_rappels(db_session)

    assert envoyes == 1
    appel = emails.call_args.kwargs
    assert appel["destinataire"] == manager.email
    assert "Rappel n°1" in appel["sujet"]
    assert "attend votre décision depuis 2 jour(s)" in appel["corps_html"]
    await db_session.refresh(etape)
    assert etape.nombre_rappels == 1 and etape.dernier_rappel_le is not None
    entree = (await db_session.execute(
        select(JournalAudit).where(JournalAudit.action == "rappel_automatique", JournalAudit.cible_id == etape.id)
    )).scalar_one()
    assert entree.details["numero_rappel"] == 1 and entree.acteur_id is None


async def test_aucun_rappel_avant_la_frequence(db_session, acteurs, emails):
    manager, employe = acteurs
    await _etape(db_session, manager, employe, heures=47)

    assert await rappels.traiter_rappels(db_session) == 0
    emails.assert_not_called()


async def test_pas_de_doublon_puis_nouveau_rappel_apres_une_periode_complete(db_session, acteurs, emails):
    manager, employe = acteurs
    _, etape = await _etape(db_session, manager, employe, heures=50)
    t0 = datetime.now(UTC)

    assert await rappels.traiter_rappels(db_session, t0) == 1
    assert await rappels.traiter_rappels(db_session, t0) == 0                        # immediatement apres
    assert await rappels.traiter_rappels(db_session, t0 + timedelta(hours=47)) == 0  # periode incomplete
    assert await rappels.traiter_rappels(db_session, t0 + timedelta(hours=49)) == 1  # periode complete

    await db_session.refresh(etape)
    assert etape.nombre_rappels == 2
    assert "Rappel n°2" in emails.call_args.kwargs["sujet"]


async def test_la_frequence_est_parametrable_et_desactivable(db_session, acteurs, emails, monkeypatch):
    manager, employe = acteurs
    await _etape(db_session, manager, employe, heures=3)

    assert await rappels.traiter_rappels(db_session) == 0  # 48 h par defaut

    monkeypatch.setattr(settings_rappels, "rappel_frequence_heures", 2.0)
    assert await rappels.traiter_rappels(db_session) == 1  # 2 h : due

    monkeypatch.setattr(settings_rappels, "rappel_frequence_heures", 0)
    assert await rappels.traiter_rappels(db_session, datetime.now(UTC) + timedelta(days=30)) == 0  # <= 0 : desactive

    monkeypatch.setattr(settings_rappels, "rappel_frequence_heures", 2.0)
    monkeypatch.setattr(settings_rappels, "rappels_automatiques_actifs", False)
    assert await rappels.traiter_rappels(db_session, datetime.now(UTC) + timedelta(days=30)) == 0


# --- qui n'est jamais relance --------------------------------------------------------

async def test_jamais_de_rappel_pour_une_demande_suspendue_terminee_annulee_ou_deja_decidee(db_session, acteurs, emails):
    manager, employe = acteurs
    # Suspendue pour precisions (ecart n°5) : l'approbateur a lui-meme suspendu sa decision.
    await _etape(db_session, manager, employe, statut=StatutEtape.EN_COURS, statut_demande=StatutDemande.COMPLEMENT_DEMANDE)
    for statut in (StatutDemande.TERMINEE, StatutDemande.REFUSEE, StatutDemande.ANNULEE):
        await _etape(db_session, manager, employe, statut_demande=statut)
    await _etape(db_session, manager, employe, statut=StatutEtape.APPROUVE)

    assert await rappels.traiter_rappels(db_session) == 0
    emails.assert_not_called()


async def test_pas_de_rappel_pour_un_approbateur_desactive_et_aucune_erreur(db_session, acteurs, emails):
    _, employe = acteurs
    parti = await _utilisateur(db_session, RoleUtilisateur.MANAGER, actif=False)
    await _etape(db_session, parti, employe)

    assert await rappels.traiter_rappels(db_session) == 0
    emails.assert_not_called()


# --- liens de decision ---------------------------------------------------------------

async def test_le_lien_du_rappel_permet_de_decider_et_l_ancien_lien_est_revoque(client, db_session, acteurs, emails):
    manager, employe = acteurs
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=1000))
    _, etape = await _etape(db_session, manager, employe)
    ancien = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", manager.id)
    await db_session.commit()
    entete = {"Authorization": f"Bearer {create_access_token(str(manager.id))}"}

    await rappels.traiter_rappels(db_session)

    assert (await client.get(f"/api/v1/decisions/{ancien}")).status_code == 401  # revoque : un seul couple actif
    jeton_approuver, jeton_refuser = _jeton_du_mail(emails)  # (lu avant la decision, qui enverra d'autres mails)
    apercu = (await client.get(f"/api/v1/decisions/{jeton_approuver}")).json()
    assert apercu["action"] == "approuver" and apercu["processus"] == "notes_frais"
    assert (await client.get(f"/api/v1/decisions/{jeton_refuser}")).json()["action"] == "refuser"
    decision = await client.post(f"/api/v1/decisions/{jeton_approuver}", json={}, headers=entete)
    assert decision.status_code == 200 and decision.json()["statut_global"] == "terminee"


async def test_un_signataire_recoit_un_lien_signer_jamais_approuver(client, db_session, acteurs, emails):
    _, employe = acteurs
    dg = await _utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    await _etape(db_session, dg, employe, processus=TypeProcessus.ACHATS, role=RoleEtape.SIGNATAIRE,
                 donnees={"tiers": "Fournisseur X", "objet": "Licences", "budget_engage": 900})

    await rappels.traiter_rappels(db_session)

    positif, _ = _jeton_du_mail(emails)
    assert (await client.get(f"/api/v1/decisions/{positif}")).json()["action"] == "signer"
    assert "signature requise" in emails.call_args.kwargs["corps_html"]
    assert ">Signer</a>" in emails.call_args.kwargs["corps_html"]


# --- contenu -------------------------------------------------------------------------

async def test_le_rappel_montre_le_solde_budgetaire_et_la_derogation(db_session, acteurs, emails):
    manager, employe = acteurs
    db_session.add(EnveloppeBudgetaire(service="Ventes", exercice=2026, budget_alloue=30))
    await db_session.commit()
    await _etape(db_session, manager, employe, derogation=True,
                 donnees={**NOTE, "montant": 500, "motif_derogation": "Urgent"})

    await rappels.traiter_rappels(db_session)

    corps = emails.call_args.kwargs["corps_html"]
    assert "Dépassement de l'enveloppe" in corps and "Solde après validation : -470.0 €" in corps
    assert "arbitrage exceptionnel (dérogation)" in corps and "Motif de dérogation : Urgent" in corps


async def test_les_champs_saisis_sont_echappes_dans_le_rappel(db_session, acteurs, emails):
    _, employe = acteurs
    dg = await _utilisateur(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    await _etape(db_session, dg, employe, processus=TypeProcessus.ACHATS,
                 donnees={"tiers": '<img src=x onerror="alert(1)">', "objet": "<script>x</script>", "budget_engage": 10})

    await rappels.traiter_rappels(db_session)

    corps = emails.call_args.kwargs["corps_html"]
    assert "<img" not in corps and "<script>" not in corps and "&lt;script&gt;" in corps


# --- fiabilite -----------------------------------------------------------------------

async def test_un_envoi_en_echec_restaure_l_etat_garde_l_ancien_lien_et_reessaie_ensuite(client, db_session, acteurs, emails):
    manager, employe = acteurs
    _, etape = await _etape(db_session, manager, employe)
    ancien = await decision_tokens.generer_jeton_decision(db_session, etape.id, "approuver", manager.id)
    await db_session.commit()
    emails.side_effect = RuntimeError("Resend indisponible")

    assert await rappels.traiter_rappels(db_session) == 0

    await db_session.refresh(etape)
    assert etape.nombre_rappels == 0 and etape.dernier_rappel_le is None       # rien de compte
    assert (await client.get(f"/api/v1/decisions/{ancien}")).status_code == 200  # l'ancien lien vit encore
    assert (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "rappel_automatique"))).first() is None

    emails.side_effect = None
    assert await rappels.traiter_rappels(db_session) == 1                       # nouvel essai au passage suivant
    await db_session.refresh(etape)
    assert etape.nombre_rappels == 1


async def test_la_reservation_est_atomique_un_seul_appelant_obtient_le_rappel(db_session, acteurs):
    manager, employe = acteurs
    _, etape = await _etape(db_session, manager, employe)
    maintenant = datetime.now(UTC)
    seuil = maintenant - timedelta(hours=48)

    premier = await rappels._reserver(db_session, etape.id, maintenant, seuil)
    second = await rappels._reserver(db_session, etape.id, maintenant, seuil)

    assert (premier, second) == (True, False)


async def test_le_lot_est_borne_et_le_reste_part_au_passage_suivant(db_session, acteurs, emails, monkeypatch):
    manager, employe = acteurs
    monkeypatch.setattr(settings_rappels, "rappel_lot_max", 2)
    for _ in range(3):
        await _etape(db_session, manager, employe)

    assert await rappels.traiter_rappels(db_session) == 2
    assert await rappels.traiter_rappels(db_session) == 1
    assert await rappels.traiter_rappels(db_session) == 0


# --- planificateur -------------------------------------------------------------------

async def test_la_boucle_repasse_regulierement_et_survit_a_une_passe_en_echec(monkeypatch):
    passes = []

    async def fausse_passe():
        passes.append(1)
        if len(passes) == 1:
            raise RuntimeError("base indisponible")
        return 0

    monkeypatch.setattr(planificateur, "une_passe", fausse_passe)
    tache = asyncio.create_task(planificateur.boucle(0.01))
    await asyncio.sleep(0.15)
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache

    assert len(passes) >= 3  # l'echec de la premiere passe n'a pas arrete la boucle


def test_le_planificateur_ne_demarre_pas_quand_les_rappels_sont_desactives(monkeypatch):
    monkeypatch.setattr(planificateur.settings, "rappels_automatiques_actifs", False)
    assert planificateur.demarrer() is None
    monkeypatch.setattr(planificateur.settings, "rappels_automatiques_actifs", True)
    monkeypatch.setattr(planificateur.settings, "rappel_frequence_heures", 0)
    assert planificateur.demarrer() is None


async def test_le_demarrage_de_l_application_lance_la_tache_et_l_extinction_l_arrete(monkeypatch):
    from app.main import app

    demarree = []

    async def dormir():
        await asyncio.sleep(3600)

    def faux_demarrer():
        tache = asyncio.create_task(dormir())
        demarree.append(tache)
        return tache

    monkeypatch.setattr(planificateur, "demarrer", faux_demarrer)
    async with app.router.lifespan_context(app):
        assert len(demarree) == 1 and not demarree[0].done()

    await asyncio.sleep(0)
    assert demarree[0].cancelled()
