"""
Pieces jointes d'une demande (CDC fonctionnel section 3) : recu des notes de frais,
justificatif d'absence des conges, documents complementaires des achats - depot
facultatif, consultation par l'approbateur.
"""
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.demande import Demande
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleEtape, RoleUtilisateur, StatutDemande, TypeProcessus
from app.models.etape_workflow import EtapeWorkflow
from app.models.journal_audit import JournalAudit
from app.models.message_clarification import MessageClarification
from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.models.user import Utilisateur
from app.services import decision_tokens, pieces

RECU = b"%PDF-1.4 " + bytes(range(256))  # octets non textuels


async def _u(db, role, email=None):
    u = Utilisateur(email=email or f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=f"Test {role.value}", service="Ventes", role=role)
    db.add(u)
    await db.commit()
    return u


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


async def _demande(db, demandeur, approbateur, processus=TypeProcessus.NOTES_FRAIS, statut=StatutDemande.EN_COURS, donnees=None):
    d = Demande(processus=processus, demandeur_id=demandeur.id, initiee_par_id=demandeur.id,
                donnees=donnees or {"montant": 50, "categorie": "Repas", "date_depense": "2026-03-01", "description": "x"},
                statut_global=statut)
    db.add(d)
    await db.flush()
    e = EtapeWorkflow(demande_id=d.id, niveau=1, role=RoleEtape.APPROBATEUR, approbateur_attendu_id=approbateur.id)
    db.add(e)
    await db.commit()
    return d, e


def _depot(client, demande, utilisateur, octets=RECU, nom="recu.pdf", mime="application/pdf"):
    return client.post(f"/api/v1/demandes/{demande.id}/pieces-jointes", files={"fichier": (nom, octets, mime)}, headers=_h(utilisateur))


@pytest.fixture
async def ctx(db_session):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    employe = await _u(db_session, RoleUtilisateur.EMPLOYE)
    return manager, employe


# --- depot ---------------------------------------------------------------------------

@pytest.mark.parametrize("processus, attendu", [
    (TypeProcessus.NOTES_FRAIS, "recu"), (TypeProcessus.CONGES, "justificatif"), (TypeProcessus.ACHATS, "complement"),
])
async def test_la_categorie_depend_du_processus_le_client_ne_la_choisit_pas(client, db_session, ctx, processus, attendu):
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager, processus=processus)

    reponse = await _depot(client, d, employe)

    assert reponse.status_code == 201
    assert reponse.json()["categorie"] == attendu and reponse.json()["nom"] == "recu.pdf"


async def test_le_depot_est_consigne_au_journal(client, db_session, ctx):
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager)
    await _depot(client, d, employe)

    entree = (await db_session.execute(select(JournalAudit).where(JournalAudit.action == "piece_jointe_ajoutee"))).scalar_one()
    assert entree.acteur_id == employe.id and entree.details == {"fichier": "recu.pdf", "categorie": "recu"}


async def test_seul_le_demandeur_depose(client, db_session, ctx):
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager)
    assert (await _depot(client, d, manager)).status_code == 403  # meme l'approbateur


async def test_depot_possible_pendant_une_suspension_refuse_sur_une_demande_close(client, db_session, ctx):
    manager, employe = ctx
    suspendue, _ = await _demande(db_session, employe, manager, statut=StatutDemande.COMPLEMENT_DEMANDE)
    assert (await _depot(client, suspendue, employe)).status_code == 201
    for statut in (StatutDemande.TERMINEE, StatutDemande.REFUSEE, StatutDemande.ANNULEE):
        close, _ = await _demande(db_session, employe, manager, statut=statut)
        assert (await _depot(client, close, employe)).status_code == 409


async def test_type_invalide_fichier_vide_trop_gros_et_trop_de_pieces(client, db_session, ctx):
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager)
    assert (await _depot(client, d, employe, nom="v.exe", mime="application/x-msdownload")).status_code == 422
    assert (await _depot(client, d, employe, octets=b"")).status_code == 422
    for _ in range(pieces.MAX_PIECES_PAR_DEMANDE):
        assert (await _depot(client, d, employe)).status_code == 201
    onzieme = await _depot(client, d, employe)
    assert onzieme.status_code == 422 and "maximal" in onzieme.json()["detail"]


MO = 1024 * 1024


async def test_taille_maximale_40_mo_pour_les_pieces_jointes(client, db_session, ctx):
    """Passee de 10 a 30 puis 40 Mo : 12 Mo (refuse avant) et exactement 40 Mo passent ; 40 Mo + 1 octet est refuse."""
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager)
    gros = b"%PDF" + b"0" * (12 * MO)
    assert (await _depot(client, d, employe, octets=gros)).status_code == 201
    limite = b"%PDF" + b"0" * (40 * MO - 4)
    assert len(limite) == 40 * MO
    assert (await _depot(client, d, employe, octets=limite)).status_code == 201
    trop = await _depot(client, d, employe, octets=limite + b"0")
    assert trop.status_code == 422 and "40 Mo" in trop.json()["detail"]


# --- consultation --------------------------------------------------------------------

async def test_le_recu_est_consultable_par_le_demandeur_l_approbateur_et_la_drh_identique_a_l_envoi(client, db_session, ctx):
    manager, employe = ctx
    drh = await _u(db_session, RoleUtilisateur.DRH)
    d, _ = await _demande(db_session, employe, manager)
    piece = (await _depot(client, d, employe)).json()

    for qui in (employe, manager, drh):
        liste = await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes", headers=_h(qui))
        assert [p["nom"] for p in liste.json()] == ["recu.pdf"]
        telechargement = await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes/{piece['id']}", headers=_h(qui))
        assert telechargement.status_code == 200 and telechargement.content == RECU


async def test_un_tiers_ne_peut_ni_lister_ni_telecharger(client, db_session, ctx):
    manager, employe = ctx
    tiers = await _u(db_session, RoleUtilisateur.MANAGER)
    d, _ = await _demande(db_session, employe, manager)
    piece = (await _depot(client, d, employe)).json()

    assert (await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes", headers=_h(tiers))).status_code == 403
    assert (await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes/{piece['id']}", headers=_h(tiers))).status_code == 403


async def test_une_piece_ne_se_lit_pas_via_le_demande_id_d_une_autre_demande(client, db_session, ctx):
    manager, employe = ctx
    autre = await _u(db_session, RoleUtilisateur.EMPLOYE)
    d_a, _ = await _demande(db_session, employe, manager)
    piece_a = (await _depot(client, d_a, employe)).json()
    d_b, _ = await _demande(db_session, autre, manager)

    # le manager est approbateur des DEUX demandes : il ne doit pas pouvoir croiser les identifiants
    reponse = await client.get(f"/api/v1/demandes/{d_b.id}/pieces-jointes/{piece_a['id']}", headers=_h(manager))
    assert reponse.status_code == 404


async def test_les_pieces_de_discussion_sont_hors_de_cette_liste_et_de_cette_route(client, db_session, ctx):
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager)
    message = MessageClarification(demande_id=d.id, auteur_id=employe.id, contenu="m")
    db_session.add(message)
    await db_session.flush()
    discussion = PieceJointe(demande_id=d.id, message_id=message.id, nom_original="d.pdf", cle_stockage="x",
                             categorie=CategoriePiece.DISCUSSION.value)
    db_session.add(discussion)
    await db_session.commit()

    assert (await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes", headers=_h(manager))).json() == []
    assert (await client.get(f"/api/v1/demandes/{d.id}/pieces-jointes/{discussion.id}", headers=_h(manager))).status_code == 404


# --- l'approbateur les voit depuis la page de decision ------------------------------------

async def test_l_apercu_de_decision_liste_les_pieces_sans_les_pieces_de_discussion(client, db_session, ctx):
    manager, employe = ctx
    d, e = await _demande(db_session, employe, manager)
    await _depot(client, d, employe, nom="ticket.pdf")
    message = MessageClarification(demande_id=d.id, auteur_id=employe.id, contenu="m")
    db_session.add(message)
    await db_session.flush()
    db_session.add(PieceJointe(demande_id=d.id, message_id=message.id, nom_original="prive.pdf", cle_stockage="x",
                               categorie=CategoriePiece.DISCUSSION.value))
    jeton = await decision_tokens.generer_jeton_decision(db_session, e.id, "approuver", manager.id)
    await db_session.commit()

    apercu = (await client.get(f"/api/v1/decisions/{jeton}")).json()

    assert [(p["nom"], p["categorie"]) for p in apercu["pieces_jointes"]] == [("ticket.pdf", "recu")]


# --- listes du demandeur -------------------------------------------------------------------

async def test_les_listes_du_demandeur_portent_les_pieces(client, db_session, ctx, monkeypatch):
    manager, employe = ctx
    d_nf, _ = await _demande(db_session, employe, manager)
    d_cg, _ = await _demande(db_session, employe, manager, processus=TypeProcessus.CONGES,
                             donnees={"type_conge_id": str(uuid.uuid4()), "date_debut": "2026-06-01", "date_fin": "2026-06-02"})
    await _depot(client, d_nf, employe, nom="recu.pdf")
    await _depot(client, d_cg, employe, nom="certificat.pdf")

    notes = (await client.get("/api/v1/notes-frais/", headers=_h(employe))).json()
    conges = (await client.get("/api/v1/conges/", headers=_h(employe))).json()

    assert [p["nom"] for p in notes[0]["pieces_jointes"]] == ["recu.pdf"]
    assert [p["nom"] for p in conges[0]["pieces_jointes"]] == ["certificat.pdf"]


# --- regression : le contrat d'un achat n'est jamais confondu avec un complement ------------

async def test_le_contrat_reste_le_contrat_meme_avec_un_complement_plus_recent(client, db_session, ctx):
    manager, employe = ctx
    d, _ = await _demande(db_session, employe, manager, processus=TypeProcessus.ACHATS,
                          donnees={"tiers": "X", "objet": "Y", "budget_engage": 10})
    from app.services import stockage_fichiers

    cle = stockage_fichiers.enregistrer_fichier(b"CONTRAT", "contrat.pdf")
    db_session.add(PieceJointe(demande_id=d.id, nom_original="contrat.pdf", cle_stockage=cle, categorie="contrat"))
    await db_session.commit()
    await _depot(client, d, employe, octets=b"%PDF complement", nom="annexe.pdf")

    reponse = await client.get(f"/api/v1/achats/{d.id}/piece-jointe", headers=_h(employe))

    assert reponse.status_code == 200 and reponse.content == b"CONTRAT"
