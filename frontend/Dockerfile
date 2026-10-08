# Frontend Next.js - image de production, multi-etapes.
#
# Ecart majeur avec l'ancien frontend Vite : ce Dockerfile ne sert PAS des
# fichiers statiques via nginx. Le proxy /api/backend/[...path] (route
# handler Next.js) a besoin d'un vrai serveur Node qui tourne en continu -
# nginx seul ne peut pas executer ce code serveur. La sortie "standalone"
# (next.config.ts) permet neanmoins une image finale legere : Next.js
# copie uniquement le serveur minimal et les dependances reellement
# utilisees, pas node_modules en entier.

# --- Etape 1 : construction ---
FROM node:22-alpine AS build
WORKDIR /srv/frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# API_BASE_URL n'est PAS necessaire au build : le proxy le lit au runtime
# (process.env.API_BASE_URL, cote serveur uniquement) - voir
# src/app/api/backend/[...path]/route.ts. Rien a figer ici.
RUN npm run build

# --- Etape 2 : image finale, serveur Node minimal ---
FROM node:22-alpine AS production
WORKDIR /srv/frontend
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    # Sans HOSTNAME=0.0.0.0, Next.js (sortie standalone) ecoute sur le nom du conteneur (variable HOSTNAME posee
    # par Docker) et refuse les connexions faites vers 127.0.0.1 : healthcheck et reverse proxy local en echec.
    HOSTNAME=0.0.0.0

# Contenu standalone genere par Next.js : serveur minimal + dependances
# reellement utilisees (pas node_modules complet). Utilisateur "node" (non root) fourni par l'image.
COPY --from=build --chown=node:node /srv/frontend/.next/standalone ./
COPY --from=build --chown=node:node /srv/frontend/.next/static ./.next/static
COPY --from=build --chown=node:node /srv/frontend/public ./public
USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# Variables a fournir au conteneur au RUNTIME (lues par le serveur Node, jamais figees dans l'image) :
#   API_BASE_URL  adresse du backend, ex. http://api:8000 ou https://backend-xxxx.apps.nubiecloud.io (OBLIGATOIRE
#                 en dehors de docker compose : le defaut http://localhost:8000 ne convient qu'en local)
#   COOKIE_SECURE laisser vide derriere HTTPS (cookies Secure par defaut en production) ; "false" uniquement
#                 pour tester l'image en http://localhost
CMD ["node", "server.js"]
