"""
Pieces jointes dans les e-mails d'une demande : les justificatifs / recus / contrats voyagent AVEC le message.

Interception au plus pres de Resend (`resend.Emails.send`) : on verifie le payload reel (`attachments`, base64,
noms) et pas une intention. Couvre les trois circuits, les e-mails de relance et d'escalade, l'envoi a la comptabilite,
l'envoi complementaire declenche par un depot APRES la soumission, le plafond de taille et la resilience.
"""
import base64

import resend

from app.models.enums import RoleUtilisateur
from app.models.piece_jointe import CategoriePiece, PieceJointe
from app.services import pieces_email, stockage_fichiers
from tests.integration.test_emails_trois_circuits import (  # noqa: F401  (fixtures et utilitaires partages)
    _a, _achat, _budget, _conges, _decider, _destinataires, _h, _jeton, _note, _u, boite,
)

PDF = b"%PDF-1.4 justificatif de test"


def _jointes(mail):
    return {a["filename"]: base64.b64decode(a["content"]) for a in mail.get("attachments", [])}


async def _deposer(client, demande_id, utilisateur, nom="recu.pdf", octets=PDF):
    return await client.post(
        f"/api/v1/demandes/{demande_id}/pieces-jointes",
        headers=_h(utilisateur), files={"fichier": (nom, octets, "application/pdf")},
    )


# ---------------------------------------------------------------- ACHATS : le contrat part avec la demande
async def test_achat_le_contrat_est_joint_au_juridique_puis_a_la_direction_generale(client, db_session, boite):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session)
    await _achat(client, emp)

    [m1] = boite
    assert _destinataires(m1) == [jur.email]
    assert _jointes(m1) == {"c.pdf": b"%PDF-1.4 x"}          # octets identiques a ceux deposes
    assert "c.pdf" in m1["html"] and "jointe à ce message" in m1["html"]

    assert (await _decider(client, _jeton(m1, "Approuver"), jur)).status_code == 200
    mail_dg = boite[1]
    assert _destinataires(mail_dg) == [dg.email] and _jointes(mail_dg) == {"c.pdf": b"%PDF-1.4 x"}
    # le demandeur, lui, n'a pas a recevoir son propre fichier en retour
    assert all("attachments" not in m for m in _a(boite, emp.email))


async def test_la_relance_rejoint_toutes_les_pieces_avec_des_noms_distincts(client, db_session, boite):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session)
    achat = await _achat(client, emp)
    assert (await _deposer(client, achat["id"], emp, "c.pdf", b"%PDF-1.4 annexe")).status_code == 201

    avant = len(boite)
    r = await client.post(f"/api/v1/achats/{achat['id']}/relancer", headers=_h(emp))
    assert r.status_code == 200 and r.json()["email_envoye"] is True
    relance = boite[avant]
    assert _destinataires(relance) == [jur.email] and "Rappel" in relance["subject"]
    assert _jointes(relance) == {"c.pdf": b"%PDF-1.4 x", "c (2).pdf": b"%PDF-1.4 annexe"}   # deux « c.pdf » : numerotes


# ---------------------------------------------------------------- NOTES DE FRAIS / CONGES : depot APRES la soumission
async def test_note_de_frais_un_depot_declenche_un_message_avec_la_piece(client, db_session, boite):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Awa Diop", manager_id=manager.id)
    await _budget(db_session)
    note = await _note(client, emp, 80.0)
    assert len(boite) == 1 and "attachments" not in boite[0]     # la demande part avant les pieces

    assert (await _deposer(client, note["id"], emp, "ticket-resto.pdf")).status_code == 201
    assert len(boite) == 2
    complement = boite[1]
    assert _destinataires(complement) == [manager.email] and complement["subject"].startswith("📎")
    assert "Awa Diop" in complement["html"] and _jointes(complement) == {"ticket-resto.pdf": PDF}


async def test_conges_le_justificatif_depose_est_envoye_au_manager(client, db_session, boite):
    emp, manager, _drh = await _conges(client, db_session, boite)
    demande_id = (await client.get("/api/v1/conges/", headers=_h(emp))).json()[0]["id"]
    assert (await _deposer(client, demande_id, emp, "certificat.pdf")).status_code == 201
    complement = boite[-1]
    assert _destinataires(complement) == [manager.email] and _jointes(complement) == {"certificat.pdf": PDF}


async def test_escalade_et_comptabilite_recoivent_les_recus(client, db_session, boite, monkeypatch):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    monkeypatch.setattr("app.routers.decisions.settings.comptabilite_email", "compta@e.com")
    note = await _note(client, emp, 700.0)
    assert (await _deposer(client, note["id"], emp, "facture-hotel.pdf")).status_code == 201

    jeton = _jeton(boite[0], "Approuver")
    assert (await _decider(client, jeton, manager)).status_code == 200
    mail_df = _a(boite, df.email)[0]
    assert _jointes(mail_df) == {"facture-hotel.pdf": PDF}
    assert (await _decider(client, _jeton(mail_df, "Approuver"), df)).status_code == 200
    mail_compta = _a(boite, "compta@e.com")[0]
    assert _jointes(mail_compta) == {"facture-hotel.pdf": PDF} and "facture-hotel.pdf" in mail_compta["html"]


# ---------------------------------------------------------------- limites, securite, resilience
async def test_plafond_de_taille_la_piece_trop_lourde_est_nommee_mais_pas_jointe(client, db_session, boite, monkeypatch):
    monkeypatch.setattr(pieces_email, "PLAFOND_OCTETS", 20)           # 20 octets : seule la 1re piece tient
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    note = await _note(client, emp, 50.0)
    assert (await _deposer(client, note["id"], emp, "petit.pdf", b"%PDF-1.4 a")).status_code == 201
    assert (await _deposer(client, note["id"], emp, "gros.pdf", b"%PDF-1.4 " + b"x" * 500)).status_code == 201

    mail_petit, mail_gros = boite[1], boite[2]       # un message par depot : chaque piece est evaluee seule
    assert list(_jointes(mail_petit)) == ["petit.pdf"]
    assert _jointes(mail_gros) == {}                  # 509 octets > plafond : non jointe ...
    assert "gros.pdf" in mail_gros["html"] and "écran de décision" in mail_gros["html"]   # ... mais signalee


async def test_les_pieces_de_la_discussion_ne_sont_jamais_jointes(client, db_session, boite):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    note = await _note(client, emp, 50.0)
    import uuid
    db_session.add(PieceJointe(
        demande_id=uuid.UUID(note["id"]), nom_original="prive.pdf", categorie=CategoriePiece.DISCUSSION.value,
        cle_stockage=stockage_fichiers.enregistrer_fichier(PDF, "prive.pdf"),
    ))
    await db_session.commit()
    resultat = await pieces_email.preparer(db_session, uuid.UUID(note["id"]))
    assert resultat.vide


async def test_un_fichier_disparu_du_stockage_n_empeche_pas_l_envoi(client, db_session, boite):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    note = await _note(client, emp, 50.0)
    assert (await _deposer(client, note["id"], emp, "perdu.pdf")).status_code == 201
    from sqlalchemy import select
    cle = (await db_session.execute(select(PieceJointe.cle_stockage))).scalars().first()
    stockage_fichiers.supprimer_fichier(cle)
    avant = len(boite)
    r = await client.post(f"/api/v1/notes-frais/{note['id']}/relancer", headers=_h(emp))
    assert r.status_code == 200 and r.json()["email_envoye"] is True
    mail = boite[avant]
    assert _jointes(mail) == {} and "perdu.pdf" in mail["html"]      # message parti, piece signalee


async def test_une_panne_de_resend_ne_bloque_pas_le_depot_d_une_piece(client, db_session, monkeypatch):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    note = await _note(client, emp, 50.0)

    def _panne(payload):
        raise RuntimeError("Resend indisponible")

    monkeypatch.setattr(resend.Emails, "send", _panne)
    r = await _deposer(client, note["id"], emp)
    assert r.status_code == 201 and r.json()["nom"] == "recu.pdf"
    liste = await client.get(f"/api/v1/demandes/{note['id']}/pieces-jointes", headers=_h(emp))
    assert [p["nom"] for p in liste.json()] == ["recu.pdf"]          # la piece est bien enregistree


async def test_un_gros_contrat_accepte_mais_trop_lourd_pour_un_e_mail_n_est_pas_joint(client, db_session, boite):
    """Limite de depot 40 Mo (07/10) > plafond d'e-mail 25 Mo : la demande part, le contrat est nomme, jamais joint."""
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session)
    gros = b"%PDF-1.4 " + b"0" * (36 * 1024 * 1024)                    # 36 Mo : accepte au depot (limite 40 Mo)
    r = await client.post("/api/v1/achats/", headers=_h(emp), data={"tiers": "Gros", "objet": "o", "budget_engage": "100"},
                          files={"fichier_contrat": ("gros-contrat.pdf", gros, "application/pdf")})
    assert r.status_code == 201, r.text
    [mail] = boite
    assert _destinataires(mail) == [jur.email]
    assert "attachments" not in mail                                  # sinon > 40 Mo une fois en base64 : Resend le refuserait
    assert "gros-contrat.pdf" in mail["html"] and "écran de décision" in mail["html"]
