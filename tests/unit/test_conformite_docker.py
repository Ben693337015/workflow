"""Conformite des fichiers Docker avec le code (aucun demon Docker requis : analyse statique)."""
import ast
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
DOCKERFILE = (RACINE / "Dockerfile").read_text(encoding="utf-8")
REQUIREMENTS = (RACINE / "requirements.txt").read_text(encoding="utf-8")
COMPOSE = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")

# nom d'import -> nom de distribution pip
ALIAS_PIP = {"botocore": "boto3", "jose": "python-jose", "PIL": "pillow", "pydantic_settings": "pydantic-settings", "jwt": "pyjwt"}


def _paquets_declares() -> set[str]:
    noms = set()
    for ligne in REQUIREMENTS.splitlines():
        ligne = ligne.split("#")[0].strip()
        if ligne:
            noms.add(re.split(r"[\[=<>~! ]", ligne)[0].lower().replace("_", "-"))
    return noms


def _imports_tiers_app() -> set[str]:
    stdlib = set(sys.stdlib_module_names)
    modules = set()
    for fichier in (RACINE / "app").rglob("*.py"):
        for noeud in ast.walk(ast.parse(fichier.read_text(encoding="utf-8"))):
            if isinstance(noeud, ast.Import):
                modules |= {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
                modules.add(noeud.module.split(".")[0])
    return {m for m in modules if m not in stdlib and m != "app"}


def _paquets_apt_production() -> set[str]:
    etape = DOCKERFILE.split("AS production")[1]
    bloc = re.search(r"apt-get install[^\n]*\\\n(.*?)&& rm -rf", etape, re.S).group(1)
    return {m.strip(" \\") for m in bloc.splitlines() if m.strip(" \\")}


def test_tout_import_tiers_du_code_est_declare_dans_requirements():
    declares = _paquets_declares()
    manquants = {
        m for m in _imports_tiers_app()
        if ALIAS_PIP.get(m, m).lower().replace("_", "-") not in declares
    }
    assert not manquants, f"Imports non declares dans requirements.txt (absents de l'image) : {manquants}"


def test_pillow_declare_explicitement():
    assert "pillow" in _paquets_declares()  # app/services/signature.py l'importe directement


def test_runtime_couvre_les_besoins_de_weasyprint_dont_les_polices():
    apt = _paquets_apt_production()
    for requis in ("libpango-1.0-0", "libpangoft2-1.0-0", "libharfbuzz0b", "libfontconfig1", "fonts-liberation"):
        assert requis in apt, f"{requis} manquant dans l'etape production"
    assert any(p.startswith("fonts-") for p in apt)


def test_runtime_sans_bibliotheques_inutiles():
    apt = _paquets_apt_production()
    assert not apt & {"libcairo2", "libpangocairo-1.0-0", "libgdk-pixbuf-2.0-0", "build-essential"}


def test_chemins_copies_existent_et_scripts_requis_presents():
    for cible in re.findall(r"^COPY (?!--from)(\S+) ", DOCKERFILE, re.M):
        assert (RACINE / cible).exists(), f"COPY {cible} : introuvable"
    assert (RACINE / "scripts/entrypoint.sh").is_file()
    assert "scripts/verification" in (RACINE / ".dockerignore").read_text()


def test_volume_pieces_jointes_identique_au_stockage_par_defaut_du_code():
    from app.core.config import Settings
    defaut = Settings.model_fields["stockage_fichiers_dossier"].default
    assert f'VOLUME ["{defaut}"]' in DOCKERFILE
    assert f"pieces_jointes:{defaut}" in COMPOSE
    assert f"/var/lib/workflows" in DOCKERFILE and "chown -R appuser" in DOCKERFILE


def test_port_healthcheck_et_commande_correspondent_a_l_application():
    assert "EXPOSE 8000" in DOCKERFILE and "0.0.0.0:8000" in DOCKERFILE
    assert "127.0.0.1:8000/health" in DOCKERFILE
    main = (RACINE / "app/main.py").read_text(encoding="utf-8")
    assert '"/health"' in main and "app = FastAPI" in main
    assert "app.main:app" in DOCKERFILE and "uvicorn.workers.UvicornWorker" in DOCKERFILE


def test_migrations_alembic_et_variables_compose_connues_du_code():
    assert (RACINE / "alembic.ini").is_file() and (RACINE / "alembic").is_dir()
    assert "RUN_MIGRATIONS" in (RACINE / "scripts/entrypoint.sh").read_text()
    from app.core.config import Settings
    champs = {n.upper() for n in Settings.model_fields}
    for var in ("DATABASE_URL", "CORS_ALLOW_ORIGINS", "FRONTEND_BASE_URL"):
        assert var in champs, f"{var} (docker-compose) n'est pas un parametre du code"


def test_frontend_dockerfile_coherent_avec_next_standalone():
    fe = RACINE / "frontend"
    df = (fe / "Dockerfile").read_text(encoding="utf-8")
    cfg = (fe / "next.config.ts").read_text(encoding="utf-8") if (fe / "next.config.ts").exists() else ""
    assert 'output: "standalone"' in cfg or "output: 'standalone'" in cfg
    assert ".next/standalone" in df and ".next/static" in df and "server.js" in df
    assert "HOSTNAME" in df and "API_BASE_URL" in df
    ign = (fe / ".dockerignore").read_text()
    assert "**/*.test.ts" in ign and ".env" in ign and "node_modules" in ign


def test_variables_s3_documentees_et_connues_du_code():
    from app.core.config import Settings
    exemple = (RACINE / ".env.example").read_text(encoding="utf-8")
    for var in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_REGION", "S3_PREFIX"):
        assert var.lower() in Settings.model_fields, f"{var} inconnu du code"
        assert re.search(rf"^{var}=", exemple, re.M), f"{var} absent de .env.example"
    # les scripts d'exploitation du stockage doivent etre dans l'image (COPY scripts) et hors .dockerignore
    ignore = (RACINE / ".dockerignore").read_text()
    for script in ("verifier_stockage.py", "migrer_fichiers_vers_s3.py"):
        assert (RACINE / "scripts" / script).is_file() and script not in ignore
