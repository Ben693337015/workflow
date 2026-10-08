"""E-mails de compte (mot de passe oublie, invitation) : habillage commun, lien exploitable, rien d'echappe a tort."""
import os
import re
import uuid

import pytest
import resend

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.enums import RoleUtilisateur
from app.models.user import Utilisateur

settings = get_settings()


@pytest.fixture
def boite(monkeypatch):
    envoyes = []
    monkeypatch.setattr(resend.Emails, "send", lambda payload: envoyes.append(payload))
    yield envoyes
    dossier = os.environ.get("EMAILS_DUMP")
    if dossier:
        os.makedirs(dossier, exist_ok=True)
        for i, m in enumerate(envoyes):
            with open(f"{dossier}/compte-{os.environ.get('PYTEST_CURRENT_TEST', 't').split('::')[1].split(' ')[0]}-{i}.html", "w", encoding="utf-8") as f:
                f.write(f"<!-- to: {m['to']} | subject: {m['subject']} -->\n{m['html']}")


async def _utilisateur(db, role, nom="Awa Ndiaye", service="Compta <b>"):
    u = Utilisateur(email=f"{role.value}-{uuid.uuid4().hex[:6]}@e.com", mot_de_passe_hash="h",
                    nom_complet=nom, service=service, role=role)
    db.add(u)
    await db.commit()
    return u


async def test_email_mot_de_passe_oublie_habille_avec_un_lien_valide(client, db_session, boite):
    u = await _utilisateur(db_session, RoleUtilisateur.EMPLOYE)
    r = await client.post("/api/v1/auth/mot-de-passe-oublie", json={"email": u.email})
    assert r.status_code == 202 and len(boite) == 1
    mail = boite[0]
    assert mail["to"] == [u.email] and mail["subject"].startswith("🔑")
    assert mail["html"].startswith("<!doctype html>") and "Choisir un nouveau mot de passe" in mail["html"]
    assert "2 heures" in mail["html"] and "Ignorez simplement ce message" in mail["html"]
    jeton = re.search(r"href='" + re.escape(settings.frontend_base_url) + r"/reinitialiser-mot-de-passe/([^']+)'>", mail["html"]).group(1)
    # le lien recu fonctionne : le nouveau mot de passe est accepte, puis la connexion reussit
    r = await client.post("/api/v1/auth/definir-mot-de-passe", json={"jeton": jeton, "mot_de_passe": "NouveauMotDePasse123!"})
    assert r.status_code == 200 and r.json()["access_token"], r.text


async def test_email_invitation_habille_et_echappe_le_service(client, db_session, boite):
    drh = await _utilisateur(db_session, RoleUtilisateur.DRH, nom="Direction RH", service="RH")
    r = await client.post(
        "/api/v1/utilisateurs/",
        json={"email": f"nouveau-{uuid.uuid4().hex[:6]}@e.com", "nom_complet": "Nouvelle Recrue", "service": "Compta <b>X</b>",
              "role": "employe"},
        headers={"Authorization": f"Bearer {create_access_token(str(drh.id))}"},
    )
    assert r.status_code == 201, r.text
    mail = boite[0]
    assert mail["subject"].startswith("👋") and "Activer mon compte" in mail["html"] and "7 jours" in mail["html"]
    assert "<b>X</b>" not in mail["html"] and "&lt;b&gt;X&lt;/b&gt;" in mail["html"]
    assert re.search(r"href='[^']*/activer-compte/[^']+'>Activer mon compte</a>", mail["html"])
