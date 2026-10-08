"""
`.env.example` doit rester synchronise avec la configuration reelle : une variable lue par l'application mais
absente du modele passe inapercue a l'installation (valeur par defaut silencieuse), une variable du modele que
l'application ne lit pas induit en erreur.
"""
import re
from pathlib import Path

from app.core.config import Settings

RACINE = Path(__file__).resolve().parents[2]
# Variables propres au script d'entree, au serveur gunicorn ou au frontend Next.js (jamais lues par Settings).
HORS_SETTINGS = {"RUN_MIGRATIONS", "WEB_CONCURRENCY", "API_BASE_URL", "COOKIE_SECURE"}


def _cles_env_example() -> set[str]:
    cles = set()
    for ligne in (RACINE / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=", ligne)
        if m:
            cles.add(m.group(1))
    return cles


def test_chaque_reglage_de_l_application_est_documente_dans_env_example():
    documentees = _cles_env_example()
    manquantes = sorted(n.upper() for n in Settings.model_fields if n.upper() not in documentees)
    assert not manquantes, f"Reglages absents de .env.example : {manquantes}"


def test_env_example_ne_documente_aucune_variable_inconnue():
    reglages = {n.upper() for n in Settings.model_fields}
    inconnues = sorted(_cles_env_example() - reglages - HORS_SETTINGS)
    assert not inconnues, f"Variables de .env.example que l'application ne lit pas : {inconnues}"


def test_les_secrets_d_exemple_sont_distincts():
    texte = (RACINE / ".env.example").read_text(encoding="utf-8")
    secret = re.search(r"^SECRET_KEY=(.*)$", texte, re.M).group(1)
    jwt = re.search(r"^JWT_SECRET_KEY=(.*)$", texte, re.M).group(1)
    assert secret != jwt
