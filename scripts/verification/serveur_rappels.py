"""
Demarre le VRAI backend (lifespan compris, donc le planificateur) sur le port 8001, avec un
envoi d'e-mail remplace par une ecriture dans /tmp/mails.log - l'envoi reel n'est pas
observable sans compte de messagerie. Voir client_rappels.py pour l'usage complet.
"""
import json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from app.services import email_service

async def faux_envoi(destinataire, sujet, corps_html):
    with open("/tmp/mails.log", "a") as f:
        f.write(json.dumps({"to": destinataire, "sujet": sujet, "corps": corps_html}) + "\n")

email_service.envoyer_email = faux_envoi
import uvicorn
from app.main import app
uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
