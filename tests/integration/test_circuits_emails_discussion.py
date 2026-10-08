"""
Parcours COMPLETS des circuits, e-mails + discussion ensemble (test de bout en bout, 07/10).

Chaque scenario deroule une demande de sa soumission a sa cloture, a travers l'API reelle, en interceptant les e-mails
au plus pres de Resend. A chaque etape on verifie QUI recoit QUOI (demandeur / approbateur / comptabilite), que les
liens recus par e-mail fonctionnent vraiment (lien de decision extrait du message puis utilise), que la discussion
suspend / reprend bien le circuit, et surtout que les etapes NON concernees ne recoivent rien (ex. en derogation, ni
le juridique ni la Direction generale).

Fixtures et utilitaires partages avec `test_emails_trois_circuits.py`.
"""
import re
import subprocess
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.demande import Demande
from app.models.enveloppe_budgetaire import EnveloppeBudgetaire
from app.models.enums import RoleUtilisateur
from tests.integration.test_emails_trois_circuits import (  # noqa: F401  (fixtures et utilitaires partages)
    ANNEE, SIGNATURE, _a, _achat, _budget, _conges, _decider, _destinataires, _h, _jeton, _liens, _note, _u,
    _verifier_tous, boite,
)

settings = get_settings()
BASE = settings.frontend_base_url.rstrip("/")


# ------------------------------------------------------------------ utilitaires de discussion
async def _suspendre(client, did, approbateur, texte):
    return await client.post(f"/api/v1/demandes/{did}/suspendre", json={"message": texte}, headers=_h(approbateur))


async def _ecrire(client, did, user, texte):
    return await client.post(f"/api/v1/demandes/{did}/messages", json={"contenu": texte}, headers=_h(user))


async def _reprendre(client, did, approbateur):
    return await client.post(f"/api/v1/demandes/{did}/reprendre", headers=_h(approbateur))


async def _messages(client, did, user):
    return await client.get(f"/api/v1/demandes/{did}/messages", headers=_h(user))


async def _texte_bon_de_commande(client, did, user, tmp_path):
    """Telecharge le bon de commande PDF et en extrait le texte (pdftotext)."""
    r = await client.get(f"/api/v1/achats/{did}/bon-de-commande", headers=_h(user))
    assert r.status_code == 200, r.text
    fichier = tmp_path / "bc.pdf"
    fichier.write_bytes(r.content)
    return " ".join(subprocess.run(["pdftotext", "-layout", str(fichier), "-"], capture_output=True, text=True,
                                    check=True).stdout.split())


def _hrefs(mail):
    return re.findall(r"href='([^']+)'", mail["html"])


def _jeton_du_lien_de_discussion(mail):
    """Le message de discussion envoye a l'APPROBATEUR porte un lien /decisions/<jeton> qui doit fonctionner."""
    [lien] = _hrefs(mail)
    assert lien.startswith(f"{BASE}/decisions/"), lien
    return lien.rsplit("/", 1)[1]


def _sujets(boite, email):
    return [m["subject"] for m in _a(boite, email)]


async def _demande(db, did):
    requete = select(Demande).where(Demande.id == uuid.UUID(did)).execution_options(populate_existing=True)
    return (await db.execute(requete)).scalar_one()


async def _enveloppe(db, service="Ventes"):
    requete = (select(EnveloppeBudgetaire).where(EnveloppeBudgetaire.service == service)
               .execution_options(populate_existing=True))
    return (await db.execute(requete)).scalar_one()


async def _achat_derogation(client, emp, budget="500", motif="Fournisseur <b>unique</b>, besoin urgent"):
    r = await client.post(
        "/api/v1/achats/", headers=_h(emp),
        data={"tiers": "Fournisseur Z", "objet": "Serveur", "budget_engage": budget,
              "derogation_motivee": "true", "motif_derogation": motif},
        files={"fichier_contrat": ("contrat.pdf", b"%PDF-1.4 contrat", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================================ ACHATS : juridique -> DG, discussion aux 2 niveaux
async def test_achat_parcours_complet_avec_discussion_a_chaque_niveau(client, db_session, boite, tmp_path):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Awa Diop")
    await _budget(db_session)

    # 1. soumission : SEUL le juridique est prevenu (pas la DG, pas la direction financiere)
    achat = await _achat(client, emp)
    did = achat["id"]
    assert [m["to"] for m in boite] == [[jur.email]]
    assert "Avis juridique requis" in boite[0]["subject"]
    jeton_initial = _jeton(boite[0], "Approuver")

    # 2. le juridique demande des precisions -> le demandeur est prevenu, la decision est gelee
    r = await _suspendre(client, did, jur, "Quelle est la durée d'engagement du contrat ?")
    assert r.status_code == 201, r.text
    mail = boite[-1]
    assert _destinataires(mail) == [emp.email] and "Précisions demandées" in mail["subject"]
    assert "engagement du contrat" in mail["html"] and _hrefs(mail) == [f"{BASE}/achats"]
    assert (await _demande(db_session, did)).statut_global.value == "complement_demande"
    assert (await _decider(client, jeton_initial, jur)).status_code == 409          # decider pendant la discussion : non

    # 3. controle d'acces de la discussion : la DG n'est pas (encore) dans l'echange
    assert (await _ecrire(client, did, dg, "Je m'invite")).status_code == 403
    assert (await _suspendre(client, did, dg, "Moi aussi")).status_code == 409        # deja en discussion

    # 4. le demandeur repond -> le JURIDIQUE reçoit un message avec un lien de decision valide
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Engagement de 12 mois, renouvelable.")).status_code == 201
    [reponse] = boite[avant:]
    assert _destinataires(reponse) == [jur.email] and "Nouveau message" in reponse["subject"]
    assert "12 mois" in reponse["html"]
    jeton_juridique = _jeton_du_lien_de_discussion(reponse)

    # 5. le juridique repond -> le DEMANDEUR est prevenu
    avant = len(boite)
    assert (await _ecrire(client, did, jur, "Merci, c'est conforme.")).status_code == 201
    [vers_emp] = boite[avant:]
    assert _destinataires(vers_emp) == [emp.email] and "conforme" in vers_emp["html"]

    # 6. reprise puis decision AVEC LE LIEN RECU PAR LA DISCUSSION -> la DG est prevenue (action « signer »)
    assert (await _reprendre(client, did, jur)).status_code == 200
    assert (await _demande(db_session, did)).statut_global.value == "en_cours"
    # hors discussion, seul l'approbateur attendu peut suspendre
    assert (await _suspendre(client, did, dg, "Pas mon tour")).status_code == 403
    assert (await _suspendre(client, did, emp, "Le demandeur ne suspend pas")).status_code == 403
    avant = len(boite)
    r = await _decider(client, jeton_juridique, jur)
    assert r.status_code == 200 and r.json()["statut_global"] == "en_cours"
    [mail_dg] = boite[avant:]
    assert _destinataires(mail_dg) == [dg.email] and {l for _j, l in _liens(mail_dg)} == {"Signer", "Refuser"}
    assert "avis favorable du service juridique" in mail_dg["html"]
    assert "c.pdf" in mail_dg["html"]                                             # le contrat suit la demande

    # 7. discussion au niveau DG : le juridique n'en fait plus partie, la DG si
    assert (await _suspendre(client, did, dg, "Le budget est-il bien arbitré avec la finance ?")).status_code == 201
    assert _destinataires(boite[-1]) == [emp.email]
    assert (await _ecrire(client, did, jur, "Je ne suis plus l'approbateur")).status_code == 403
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Oui, validé avec la finance.")).status_code == 201
    [reponse_dg] = boite[avant:]
    assert _destinataires(reponse_dg) == [dg.email]
    jeton_signature = _jeton_du_lien_de_discussion(reponse_dg)
    assert (await _reprendre(client, did, dg)).status_code == 200

    # 8. signature avec le lien de la discussion -> circuit termine, budget debite, BC attribue
    avant = len(boite)
    r = await _decider(client, jeton_signature, dg, {"signature_image_base64": SIGNATURE})
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    final = boite[avant:]
    assert [m["to"] for m in final] == [[emp.email]] and "approuvée" in final[0]["subject"]
    assert "avis juridique" in final[0]["html"].lower() and "Direction générale" in final[0]["html"]
    assert (await _enveloppe(db_session)).budget_consomme == 100
    assert (await _demande(db_session, did)).donnees.get("numero_bc")
    bc = await _texte_bon_de_commande(client, did, emp, tmp_path)               # circuit standard : juridique + DG
    assert "Service juridique — Avis favorable" in bc and "Direction générale — Signé électroniquement" in bc
    assert "Arbitrage exceptionnel" not in bc and "introuvable" not in bc

    # 9. la discussion est close : plus de message, l'historique reste lisible par le demandeur
    assert (await _ecrire(client, did, emp, "Trop tard")).status_code == 409
    historique = (await _messages(client, did, emp)).json()
    assert [m["auteur_nom"] for m in historique].count("Awa Diop") == 2 and len(historique) == 5
    _verifier_tous(boite)
    # le demandeur n'a jamais recu d'e-mail de decision avant la fin
    assert not [s for s in _sujets(boite, emp.email) if "approuvée" in s][:-1]


async def test_achat_refus_du_juridique_apres_discussion_ferme_le_circuit(client, db_session, boite):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session)
    achat = await _achat(client, emp)
    did = achat["id"]
    assert (await _suspendre(client, did, jur, "Clause de résiliation absente ?")).status_code == 201
    assert (await _ecrire(client, did, emp, "Non, elle n'y est pas.")).status_code == 201
    assert (await _reprendre(client, did, jur)).status_code == 200
    jeton_refus = next(j for j, l in _liens(boite[0]) if l == "Refuser")
    avant = len(boite)
    r = await _decider(client, jeton_refus, jur, {"commentaire": "Clause de résiliation manquante"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    final = boite[avant:]
    assert [m["to"] for m in final] == [[emp.email]]                              # ni DG ni autre
    assert "refusée" in final[0]["subject"] and "résiliation manquante" in final[0]["html"]
    assert not _a(boite, dg.email)
    assert (await _enveloppe(db_session)).budget_consomme == 0                     # rien de debite
    assert (await _ecrire(client, did, emp, "Et maintenant ?")).status_code == 409
    _verifier_tous(boite)


# ============================================================================ NOTES DE FRAIS : manager -> DF au-dela du seuil
async def test_note_de_frais_au_dela_du_seuil_avec_discussion_puis_comptabilite(client, db_session, boite, monkeypatch):
    monkeypatch.setattr("app.routers.decisions.settings.comptabilite_email", "compta@e.com")
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Karim Fofana", manager_id=manager.id)
    await _budget(db_session)

    note = await _note(client, emp, 700.0)
    did = note["id"]
    assert [m["to"] for m in boite] == [[manager.email]]

    # niveau 1 : discussion avec le manager puis approbation -> escalade DF (le demandeur n'est pas notifie de la decision)
    assert (await _suspendre(client, did, manager, "Un justificatif de plus ?")).status_code == 201
    assert _destinataires(boite[-1]) == [emp.email]
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Voici le détail, tout est joint.")).status_code == 201
    jeton_manager = _jeton_du_lien_de_discussion(boite[avant])
    assert _destinataires(boite[avant]) == [manager.email]
    assert (await _reprendre(client, did, manager)).status_code == 200
    avant = len(boite)
    assert (await _decider(client, jeton_manager, manager)).status_code == 200
    assert [m["to"] for m in boite[avant:]] == [[df.email]]                       # DF seule prevenue
    assert "montant élevé" in boite[avant]["subject"].lower()
    mail_df = boite[avant]
    assert not [s for s in _sujets(boite, emp.email) if "approuvée" in s]

    # niveau 2 : le manager n'est plus dans l'echange, la DF si
    assert (await _suspendre(client, did, manager, "Je rouvre")).status_code == 403
    assert (await _suspendre(client, did, df, "Quel projet est imputé ?")).status_code == 201
    assert (await _ecrire(client, did, manager, "Je ne suis plus l'approbateur")).status_code == 403
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Projet Atlas.")).status_code == 201
    assert _destinataires(boite[avant]) == [df.email]
    jeton_df = _jeton_du_lien_de_discussion(boite[avant])
    assert (await _reprendre(client, did, df)).status_code == 200

    # approbation finale : comptabilite + demandeur, et uniquement eux
    avant = len(boite)
    r = await _decider(client, jeton_df, df)
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    final = boite[avant:]
    assert sorted(m["to"][0] for m in final) == sorted(["compta@e.com", emp.email])
    assert "à rembourser" in _a(final, "compta@e.com")[0]["subject"]
    assert "approuvée" in _a(final, emp.email)[0]["subject"]
    assert (await _enveloppe(db_session)).budget_consomme == 700
    # l'ancien lien (mail initial du DF) ne decide pas une seconde fois
    assert (await _decider(client, _jeton(mail_df, "Approuver"), df)).status_code in (400, 401, 409)
    _verifier_tous(boite)


async def test_note_de_frais_refus_de_la_direction_financiere_pas_de_comptabilite(client, db_session, boite, monkeypatch):
    monkeypatch.setattr("app.routers.decisions.settings.comptabilite_email", "compta@e.com")
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    await _note(client, emp, 900.0)
    await _decider(client, _jeton(boite[0], "Approuver"), manager)
    avant = len(boite)
    r = await _decider(client, _jeton(boite[1], "Refuser"), df, {"commentaire": "Dépense non éligible"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    final = boite[avant:]
    assert [m["to"] for m in final] == [[emp.email]] and "refusée" in final[0]["subject"]
    assert "non éligible" in final[0]["html"]
    assert not _a(boite, "compta@e.com")
    assert (await _enveloppe(db_session)).budget_consomme == 0
    _verifier_tous(boite)


# ============================================================================ CONGES
async def test_conges_avec_discussion_puis_approbation(client, db_session, boite):
    emp, manager, drh = await _conges(client, db_session, boite)
    did = next(iter((await client.get("/api/v1/conges/", headers=_h(emp))).json()))["id"]
    assert (await _suspendre(client, did, manager, "Quelqu'un te remplace ?")).status_code == 201
    assert _destinataires(boite[-1]) == [emp.email] and _hrefs(boite[-1]) == [f"{BASE}/mes-demandes"]
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Oui, Marie prend le relais.")).status_code == 201
    jeton = _jeton_du_lien_de_discussion(boite[avant])
    assert _destinataires(boite[avant]) == [manager.email]
    assert (await _reprendre(client, did, manager)).status_code == 200
    avant = len(boite)
    r = await _decider(client, jeton, manager)
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    assert sorted(m["to"][0] for m in boite[avant:]) == sorted([drh.email, emp.email])
    _verifier_tous(boite)


# ============================================================================ DEROGATION : un seul arbitre, personne d'autre
async def test_derogation_achat_va_directement_a_l_arbitre_et_court_circuite_juridique_et_dg(client, db_session, boite, tmp_path):
    jur = await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    ctrl = await _u(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Awa Diop")
    await _budget(db_session, alloue=100)                              # achat de 500 : depassement + derogation motivee

    achat = await _achat_derogation(client, emp)
    did = achat["id"]
    assert achat["derogation"] is True
    # SEUL l'arbitre est prevenu ; juridique et DG ne recoivent rien
    assert [m["to"] for m in boite] == [[ctrl.email]]
    mail = boite[0]
    assert "Arbitrage requis" in mail["subject"] and "Fournisseur" in mail["html"] and "<b>unique</b>" not in mail["html"]
    assert "contrat.pdf" in mail["html"]
    assert {l for _j, l in _liens(mail)} == {"Approuver", "Refuser"}              # pas de « Signer » : pas de signature en derogation

    # discussion avec l'arbitre
    assert (await _suspendre(client, did, ctrl, "Y a-t-il un devis concurrent ?")).status_code == 201
    assert (await _ecrire(client, did, jur, "Je suis le juridique")).status_code == 403       # le juridique n'est pas dans l'echange
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Deux devis, celui-ci est le moins cher.")).status_code == 201
    jeton = _jeton_du_lien_de_discussion(boite[avant])
    assert _destinataires(boite[avant]) == [ctrl.email]
    assert (await _reprendre(client, did, ctrl)).status_code == 200

    # la justification est obligatoire pour accepter (et le jeton n'est pas brule par l'erreur)
    r = await _decider(client, jeton, ctrl)
    assert r.status_code == 422 and "justification" in r.json()["detail"].lower()
    avant = len(boite)
    r = await _decider(client, jeton, ctrl, {"justification_acceptation": "Meilleur devis, urgence confirmée"})
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    final = boite[avant:]
    assert [m["to"] for m in final] == [[emp.email]] and "approuvée" in final[0]["subject"]
    assert not _a(boite, jur.email) and not _a(boite, dg.email)                   # jamais sollicites
    # budget debite meme au-dela de l'enveloppe (derogation) et BC attribue
    assert (await _enveloppe(db_session)).budget_consomme == 500
    assert (await _demande(db_session, did)).donnees.get("numero_bc")
    # le message au demandeur ne doit pas pretendre que des validations contournees ont eu lieu
    corps = final[0]["html"].lower()
    assert "avis juridique" not in corps and "direction générale" not in corps, final[0]["html"]
    assert "dérogation" in corps or "arbitrage" in corps
    # le bon de commande dit la meme verite : arbitrage exceptionnel, pas de faux avis juridique ni de signature DG
    bc = await _texte_bon_de_commande(client, did, emp, tmp_path)
    assert "Arbitrage exceptionnel (dérogation)" in bc and ctrl.nom_complet in bc and "besoin urgent" in bc
    assert "Avis favorable" not in bc and "Signé électroniquement" not in bc and "introuvable" not in bc
    _verifier_tous(boite)


async def test_derogation_achat_refusee_motif_au_demandeur_rien_n_est_debite(client, db_session, boite):
    await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    ctrl = await _u(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION, service="Finance")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, alloue=100)
    achat = await _achat_derogation(client, emp)
    avant = len(boite)
    r = await _decider(client, _jeton(boite[0], "Refuser"), ctrl, {"commentaire": "Budget <i>gelé</i> ce trimestre"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    final = boite[avant:]
    assert [m["to"] for m in final] == [[emp.email]] and "refusée" in final[0]["subject"]
    assert "gelé" in final[0]["html"] and "<i>" not in final[0]["html"]
    assert (await _enveloppe(db_session)).budget_consomme == 0
    assert "numero_bc" not in (await _demande(db_session, achat["id"])).donnees
    _verifier_tous(boite)


async def test_derogation_note_de_frais_depassement_automatique_par_la_direction_financiere_seule(client, db_session, boite, monkeypatch):
    monkeypatch.setattr("app.routers.decisions.settings.comptabilite_email", "compta@e.com")
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    df = await _u(db_session, RoleUtilisateur.DIRECTION_FINANCIERE, service="Finance")
    ctrl_inutile = await _u(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION, service="Finance")
    dg_inutile = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    ctrl = df                                           # l'arbitre d'une note de frais en derogation
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, nom="Karim Fofana", manager_id=manager.id)
    await _budget(db_session, alloue=100)
    # depassement budgetaire detecte automatiquement : sans motif -> refuse a la soumission
    r = await client.post("/api/v1/notes-frais/", headers=_h(emp), json={
        "montant": 900, "categorie": "Repas", "date_depense": f"{ANNEE}-03-01", "description": "x"})
    assert r.status_code == 422 and "motif de dérogation" in r.json()["detail"].lower()
    assert not boite
    # avec motif (pas de case cochee : c'est le depassement qui declenche)
    note = await _note(client, emp, 900.0, {"motif_derogation": "Salon client"})
    did = note["id"]
    assert [m["to"] for m in boite] == [[ctrl.email]]                              # ni manager, ni Controleur, ni DG (900 > seuil !)
    assert "dépassement budgétaire détecté automatiquement" in boite[0]["html"]

    # discussion puis acceptation : un seul niveau malgre le montant > seuil
    assert (await _suspendre(client, did, ctrl, "Le client a-t-il signé ?")).status_code == 201
    avant = len(boite)
    assert (await _ecrire(client, did, emp, "Oui, contrat signé hier.")).status_code == 201
    jeton = _jeton_du_lien_de_discussion(boite[avant])
    assert (await _reprendre(client, did, ctrl)).status_code == 200
    assert (await _suspendre(client, did, manager, "Hors circuit")).status_code == 403
    avant = len(boite)
    r = await _decider(client, jeton, ctrl, {"justification_acceptation": "Retombées commerciales confirmées"})
    assert r.status_code == 200 and r.json()["statut_global"] == "terminee"
    final = boite[avant:]
    assert sorted(m["to"][0] for m in final) == sorted(["compta@e.com", emp.email])
    assert not _a(boite, manager.email) and not _a(boite, ctrl_inutile.email) and not _a(boite, dg_inutile.email)
    assert (await _enveloppe(db_session)).budget_consomme == 900
    _verifier_tous(boite)


async def test_derogation_achat_repli_sur_la_direction_generale_quand_il_n_y_a_pas_de_controleur(client, db_session, boite):
    """ACHATS uniquement : Controleur de gestion, a defaut Direction generale (les notes de frais n'ont aucun repli)."""
    await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    dg = await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, alloue=100)
    await _achat_derogation(client, emp)
    assert [m["to"] for m in boite] == [[dg.email]] and "Arbitrage requis" in boite[0]["subject"]
    avant = len(boite)
    r = await _decider(client, _jeton(boite[0], "Refuser"), dg, {"commentaire": "Pas d'exception"})
    assert r.status_code == 200 and r.json()["statut_global"] == "refusee"
    assert [m["to"] for m in boite[avant:]] == [[emp.email]]
    _verifier_tous(boite)


async def test_derogation_note_de_frais_sans_direction_financiere_refus_propre_sans_rien_envoyer(client, db_session, boite):
    manager = await _u(db_session, RoleUtilisateur.MANAGER)
    await _u(db_session, RoleUtilisateur.CONTROLEUR_DE_GESTION, service="Finance")      # present mais exclu
    await _u(db_session, RoleUtilisateur.DIRECTION_GENERALE, service="Direction")       # present mais exclu
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE, manager_id=manager.id)
    await _budget(db_session)
    r = await client.post("/api/v1/notes-frais/", headers=_h(emp), json={
        "montant": 50, "categorie": "Repas", "date_depense": f"{ANNEE}-03-01", "description": "x",
        "derogation_motivee": True, "motif_derogation": "Exception"})
    assert r.status_code == 422, r.text
    assert "direction financière" in r.json()["detail"].lower()
    assert not boite


async def test_derogation_achat_sans_aucun_arbitre_refuse_proprement_sans_rien_envoyer(client, db_session, boite):
    await _u(db_session, RoleUtilisateur.SERVICE_JURIDIQUE, service="Juridique")
    emp = await _u(db_session, RoleUtilisateur.EMPLOYE)
    await _budget(db_session, alloue=100)
    r = await client.post(
        "/api/v1/achats/", headers=_h(emp),
        data={"tiers": "Z", "objet": "Serveur", "budget_engage": "500", "derogation_motivee": "true", "motif_derogation": "x"},
        files={"fichier_contrat": ("c.pdf", b"%PDF-1.4 c", "application/pdf")},
    )
    assert r.status_code in (409, 422), r.text
    assert "arbitrage" in r.json()["detail"].lower()
    assert not boite
