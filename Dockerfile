# Backend FastAPI - image de production, multi-etapes.
# Correspond a la section 3.3 / 14.1 du CDC technique :
# conteneur Docker executant Uvicorn derriere Gunicorn, deploye via NubiDeploy.
#
# Ecart identifie (23/09) : la version mono-etape precedente conservait
# build-essential/gcc/g++/binutils dans l'image finale - necessaires
# uniquement pour `pip install`, jamais a l'execution (tous les paquets de
# requirements.txt s'installent depuis des wheels precompiles, sans
# compilation source). Consequence mesuree : scan de securite a 30
# vulnerabilites (3 critiques, 27 elevees), probable cause d'un blocage de
# deploiement sur NubieCloud (statut "RUNNING" sans "ressource
# restartable" malgre un build reussi). Version multi-etapes : les outils
# de compilation restent dans l'etape de build, jetee ensuite.

# --- Etape 1 : construction (outils de build, jetes ensuite) ---
FROM python:3.12-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

# Outils de compilation + versions -dev des libs WeasyPrint, necessaires
# uniquement si pip doit compiler une extension C depuis les sources
# (filet de securite si une future dependance n'a pas de wheel precompile).
#
# IMPORTANT : l'image python:3.12-slim est basee sur Debian trixie, qui a
# retire le paquet transitoire "libgdk-pixbuf2.0-0" (renomme en amont par
# Debian en "libgdk-pixbuf-2.0-0", tiret avant "2.0"). Si ce build echoue a
# nouveau avec un message "has no installation candidate" pour un paquet
# systeme, c'est tres probablement le meme type de renommage cote Debian -
# chercher le nouveau nom avec `apt-cache search <nom-approximatif>`.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango1.0-dev \
    libcairo2-dev \
    libgdk-pixbuf-2.0-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Environnement virtuel isole, pour ne copier que ce qui est reellement
# necessaire dans l'etape finale (pas les outils de build).
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Etape 2 : image finale, sans compilateur ni paquets -dev ---
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

# Bibliotheques partagees (.so) requises par WeasyPrint a l'execution -
# equivalent runtime des paquets -dev de l'etape de build, sans les
# en-tetes de compilation ni les compilateurs.
# poppler-utils (pdftotext) n'est pas requis en production : seule la suite de tests l'utilise
# (tests/unit/test_documents.py), et les tests ne sont pas dans l'image (.dockerignore) : on les lance depuis
# la machine hote (voir README, « Lancer les tests »).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libharfbuzz-subset0 \
    libfontconfig1 \
    fontconfig \
    fonts-liberation \
    fonts-dejavu-core \
    libffi8 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
# WeasyPrint 63 n'utilise ni cairo ni gdk-pixbuf (rendu par Pango/HarfBuzz + Pillow pour les images) : ces
# bibliotheques ne sont plus installees a l'execution. Les POLICES sont indispensables : l'image slim n'en
# contient aucune, et sans elles les PDF (bon de commande, fiche d'absence) sortiraient sans texte lisible.

# Copie de l'environnement virtuel deja construit (paquets Python
# uniquement, pas les outils de compilation).
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

# Utilisateur non privilegie : le serveur n'a aucune raison de tourner en root. Le dossier des pieces jointes
# (contrats, justificatifs, recus) lui appartient ; il est declare comme VOLUME : MONTEZ-LE sur un stockage
# persistant (volume nomme, disque) sinon les fichiers deposes disparaissent avec le conteneur.
RUN useradd --system --no-create-home --uid 10001 appuser \
    && mkdir -p /var/lib/workflows/pieces-jointes \
    && chown -R appuser:appuser /var/lib/workflows /srv/app
USER appuser
VOLUME ["/var/lib/workflows/pieces-jointes"]

# Nombre de processus : variable WEB_CONCURRENCY (lue par gunicorn), 4 par defaut.
ENV WEB_CONCURRENCY=4

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

ENTRYPOINT ["sh", "/srv/app/scripts/entrypoint.sh"]
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000"]
