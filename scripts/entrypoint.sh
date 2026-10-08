#!/bin/sh
# Point d'entree de l'image backend.
#
# - RUN_MIGRATIONS=true : applique `alembic upgrade head` AVANT de demarrer le serveur. Pratique en
#   developpement (docker compose le met a true) et pour un deploiement a instance unique. Avec plusieurs
#   instances du backend, laissez la valeur par defaut (false) et lancez les migrations une seule fois, par
#   une tache dediee (`alembic upgrade head`) : deux instances qui migrent en meme temps se gênent.
# - Puis la commande de l'image (gunicorn) ou celle de docker compose (uvicorn --reload) est executee telle quelle.
set -e

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
fi

exec "$@"
