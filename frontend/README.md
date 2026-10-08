# Frontend — Plateforme d'approbation de workflows

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4 + shadcn/ui. Écrans : congés, notes de frais,
achats, discussion demandeur ↔ approbateur, page de décision publique (lien e-mail), agenda d'équipe, synthèse des
frais, journal d'audit et administration (comptes et managers, types de congé, soldes, budgets, devises). Le
README racine détaille l'installation complète (Docker, production, dépannage).

## Démarrer en local

```bash
npm install          # Node ≥ 20 (l'image Docker utilise Node 22)
npm run dev          # http://localhost:3000
```

Le proxy API (voir plus bas) relaie par défaut vers `http://localhost:8000` : lancer le backend FastAPI avant.

## Tests

```bash
npm test             # Vitest + jsdom + React Testing Library (229 tests)
npx tsc --noEmit     # vérification des types
```

Les parcours de bout en bout dans un vrai navigateur (Playwright, Chromium) sont dans
`../scripts/verification/interface/` (voir son README).

## Build de production

```bash
npm run build        # puis : node .next/standalone/server.js
```

Sortie `standalone` (`next.config.ts`) : le serveur minimal est dans `.next/standalone/server.js`. En production il
faut aussi y copier `.next/static` (vers `.next/standalone/.next/static`) et `public` : le `Dockerfile` le fait. Le
build n'a besoin d'aucune variable d'environnement ni d'accès réseau (polices Manrope auto-hébergées via
`@fontsource-variable/manrope`).

## Architecture — le proxy API

`src/app/api/backend/[...path]/route.ts` relaie chaque appel du navigateur vers le backend FastAPI. Le navigateur
n'appelle jamais que `/api/backend/...` (même origine) ; l'URL réelle du backend est lue **côté serveur, à chaque
requête**, via `API_BASE_URL` — jamais inlinée dans le JavaScript envoyé au navigateur. Changer de backend ne
demande donc aucun rebuild, juste un redémarrage avec une nouvelle valeur. Aucun CORS à configurer.

Le proxy porte aussi la **session** : à la connexion, il place les jetons dans des cookies `httpOnly` (invisibles du
JavaScript de la page) et les réinjecte lui-même dans les appels au backend ; il gère le rafraîchissement et la
déconnexion (`/api/backend/api/v1/auth/deconnexion`, propre au proxy). `src/lib/api.ts` est le client API : toutes
ses fonctions passent par ce proxy.

## Variables d'environnement

Toutes sont lues par le **serveur** Next.js au runtime ; aucune ne part vers le navigateur et il n'existe aucune
variable `NEXT_PUBLIC_*`.

| Variable | Défaut | Rôle |
|---|---|---|
| `API_BASE_URL` | `http://localhost:8000` | Adresse du backend FastAPI. Dans Docker Compose : `http://api:8000`. **À renseigner** en dehors de ce cas |
| `COOKIE_SECURE` | `true` en production, `false` en développement | `true` : cookies de session envoyés uniquement en HTTPS. Mettre `false` seulement pour tester une image de production en `http://localhost` — jamais derrière un vrai domaine |
| `PORT` / `HOSTNAME` | `3000` / `0.0.0.0` dans l'image | Écoute du serveur Node (`HOSTNAME=0.0.0.0` est nécessaire en conteneur) |

## Docker

- `Dockerfile` : production, multi-étapes (`npm ci` + `next build`, puis un serveur Node minimal exécuté par
  l'utilisateur non privilégié `node`, avec `HEALTHCHECK` sur `/login`).
- `Dockerfile.dev` : développement avec rechargement à chaud (utilisé par `docker-compose.yml`, qui monte
  `src/` et `public/`).

## Structure

```
src/
  app/
    (app)/            # Écrans authentifiés (barre latérale + mise en page commune) :
                      #   mes-demandes, nouvelle-demande, notes-frais, achats, regularisation,
                      #   agenda-equipe, synthese-frais, journal-audit, admin
    api/backend/[...path]/route.ts   # Proxy vers le backend FastAPI (+ session par cookies httpOnly)
    decisions/[jeton]/               # Page de décision publique (lien e-mail)
    login/, mot-de-passe-oublie/, activer-compte/[jeton]/, reinitialiser-mot-de-passe/[jeton]/
  components/
    layout/           # Sidebar (tiroir mobile), UserMenu
    ui/               # Primitives (Button, Card, Input, Select, Badge, Table, Squelette...)
  hooks/useAuth.tsx   # Contexte d'authentification (session, connexion, déconnexion)
  lib/api.ts          # Client API (passe par le proxy /api/backend)
  types/index.ts      # Types alignés sur les schémas Pydantic du backend
```
