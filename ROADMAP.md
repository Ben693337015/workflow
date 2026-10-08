# Roadmap — Plateforme d'Approbation de Workflows

**Dernière mise à jour : 30 septembre 2026** — réalignée sur l'état réel du code après la campagne de
correction des défauts. Référence : *Cahier des Charges Technique* V2.8.

> **Règle de tenue de ce fichier** : chaque ligne « Fait » doit être vérifiable dans le code ou par une
> commande citée. Chaque ligne « Reste à faire » cite le fichier ou la preuve d'absence.

---

## 1. Où en est le projet

Les trois processus (congés, notes de frais, achats/contrats) ont un circuit réel de bout en bout, backend
et frontend. **Les défauts d'intégrité et de sécurité relevés à la relecture du code sont corrigés** (§3).
Reste : les règles RH non appliquées, les webhooks, quelques durcissements, et tout le déploiement.

| Volet | État | Preuve |
|---|---|---|
| Backend FastAPI (~8 300 lignes, **18 tables**, **15 migrations**) | Livré | `alembic upgrade head` depuis zéro, PostgreSQL et SQLite : aucune dérive (`alembic check`) |
| Frontend Next.js + React + Tailwind + shadcn/ui | Livré | `next build` réussi |
| Tests backend | **444 passent**, 3 ignorés | `pytest` (les 3 ignorés = tests PostgreSQL, voir ci-dessous) |
| Tests de concurrence sur vrai PostgreSQL | **3 passent** | `WORKFLOWS_TEST_POSTGRES_URL=... pytest tests/postgres` |
| Tests frontend | **222 passent** | `npx vitest run` ; `tsc --noEmit` propre ; `next build` réussi |
| Fichiers déposés : limite **40 Mo** (10 Mo → 30 Mo le 05/10 → 40 Mo le 07/10) | **13/13** de bout en bout | `scripts/verification/interface/fichiers_40mo_e2e.py` : 12 Mo, 30 Mo + 1 (ancienne limite) accepté, 40 Mo exactement (relu octet pour octet), 40 Mo + 1 refusé ; contrat de 39 Mo par le formulaire ; 41 Mo refusé avant envoi ; discussion avec 38 Mo |
| Interface en vrai navigateur (Chromium) | **0 débordement** à 1332, 1024, 768, 390 px ; **discussion demandeur ↔ approbateur : 6/6** (congés, notes de frais, achats × 1332 px et 390 px), deux navigateurs, pièce jointe téléchargée, lien ouvert sans session | `scripts/verification/interface/` ; développement **et** build de production |
| Vérification de bout en bout, PostgreSQL + rôle restreint | **19/19** | `scripts/verification/verifier_corrections_postgres.py` |
| Session par cookies, vrai Next.js + vrai backend | Vérifiée en HTTP **et dans Chromium** | connexion par le formulaire, cookies `HttpOnly`/`Strict`, aucun jeton lisible par le JavaScript ; **Firefox/Safari non testés** |
| Déploiement NubieCloud (PostgreSQL NubiStack, NubiS3, NubiDeploy) | **Non fait** | — |
| Domaine Resend vérifié / envoi réel | **Non fait** | `email_envoye` toujours `false` en test |

---

## 2. Ce qui est fait (vérifié)

### Cadrage et décisions
- CDC technique V2.8 ; FastAPI / PostgreSQL / SQLAlchemy / Resend ; Option B (jeton + session) implémentée ; Next.js (React) + Tailwind + shadcn/ui.

### Backend
- Auth JWT + refresh, bcrypt, `get_current_user`, rôles ; invitation/activation de compte, réinitialisation de mot de passe.
- **Limitation des connexions échouées** : verrouillage 15 min après 5 échecs, compteur atomique, traces d'audit.
- Jetons de décision opaques hachés SHA-256 ; moteur de routage séquentiel, dynamique, conditionnel par seuil de montant converti.
- **Congés** : verrou RH avec **réservation du solde sous verrou de ligne**, journal `mouvements_conges`, libération au refus/annulation/modification, confirmation à l'approbation ; types de congé, jours fériés, régularisation, annulation, modification ; **jours entiers imposés** ; option d'exclusion des week-ends.
- **Notes de frais** : circuit à seuil, synthèse comptabilité (CSV), multi-devises avec taux figé.
- **Achats/contrats** : contrat obligatoire, Juridique puis Direction générale (signature), bon de commande PDF, TVA par ligne, **numérotation par compteur verrouillé**.
- Suivi budgétaire (débit atomique), dérogations, discussion bidirectionnelle, pièces jointes, rappels automatiques, relance manuelle, annulation.
- **Décision atomique** : étape, demande, jeton, débit et numéro de bon de commande dans une seule transaction.
- Journal d'audit append-only (déclencheurs, garde ORM, rôle restreint) ; journal des mouvements de congés protégé de même dans `roles_postgresql.sql`.
- **Secrets webhook chiffrés au repos** (Fernet), migration des secrets existants.
- Webhooks sortants : signature HMAC, déclenchement depuis les routeurs (**version minimale, voir §4**).

### Frontend
- **Session par cookies `httpOnly` + `SameSite=Strict`** posés par le proxy Next.js ; le JavaScript ne voit plus aucun jeton.
- Toutes les pages (connexion, activation, demandes, décision publique, régularisation, agenda, synthèse, audit, administration).
- Le formulaire d'activation de compte, qui n'avait aucun test, en a désormais quatre.

---

## 3. Défauts relevés le 29/09 — tous traités

| Réf. | Défaut | Statut | Comment c'est prouvé |
|---|---|---|---|
| R17 | Pas de réservation du solde de congés (double comptage possible) | **Corrigé** | 8 soumissions simultanées sur vrai PostgreSQL : 1 seule acceptée ; retrait du `FOR UPDATE` fait échouer les tests |
| R18 | Décision et débit dans deux transactions | **Corrigé** | test d'incident pendant le débit : rien n'est enregistré ; mutation détectée |
| R19 | `GET /api/v1/conges/{id}` sans authentification | **Corrigé** | 7 tests d'accès ; mutation détectée |
| R20 | « jours ouvrés » affiché, jours calendaires comptés | **Partiel** | libellé corrigé, option `CONGES_EXCLURE_WEEKENDS`. **Décision DRH toujours nécessaire** (G2bis) : le comportement par défaut n'a pas changé |
| R21 | Numéro de bon de commande par comptage | **Corrigé** | 12 attributions simultanées sur vrai PostgreSQL : 12 numéros distincts ; reprise des numéros existants testée à la migration, doublon existant inclus |
| R22 | Secret HMAC des webhooks en clair | **Corrigé** | 13 tests ; migration testée (chiffre, déchiffre, rejouable) ; mutation détectée |
| R23 | Jetons JWT dans `localStorage` | **Corrigé** | 22 tests du proxy + parcours réel : cookies `HttpOnly; SameSite=strict`, aucun jeton dans les corps de réponse ; mutations détectées (httpOnly, corps, SameSite) |
| R24 | Écarts de modèle avec le CDC | **Partiel, assumé** | fait : clé étrangère `manager_id`, JSONB, `mouvements_conges`, `bons_commande`. **Non fait** (décision, pas oubli) : colonnes dénormalisées montant/dates, rattachement des enveloppes à un code analytique, `types_demande` inutilisée |
| R9 | Pas de limitation des connexions | **Corrigé** | 10 tests ; mutation détectée ; vérifié via le proxy réel (429 + `Retry-After`) |
| R4 | `CONGES_UNITE_JOUR_ENTIER` jamais lu | **Corrigé** | un solde en demi-journée est refusé (422) |
| UI-1 | La barre latérale remontait avec la page et sortait de l'écran (signalé par capture d'écran) | **Corrigé** | Mesuré dans Chromium : avant, `bottom: 295` après défilement ; après, `top: 0 / bottom: 679`, la fenêtre ne défile plus ; 8 tests de structure, 4 mutations détectées |
| UI-2 | Tableaux coupés (colonne « Actions » invisible, noms de fichiers tronqués), textes longs qui débordent | **Corrigé** | Audit automatique : 156 signalements avant, **0** après, sur 4 largeurs ; vérifié aussi sur le build de production |
| — | `npm ci` échouait → image frontend de production impossible à construire | **Corrigé** | `@types/node` aligné sur Node 22 ; `npm ci` puis `next build` réussis |

---

## 4. Reste à faire — par priorité

### P0 — Écarts avec le CDC ou les décisions actées

| # | Tâche | Preuve dans le code | CDC |
|---|---|---|---|
| R1 | **Appliquer le plafond de report de 10 jours (D2a)** : le code applique toujours un report illimité | `config.py` : `conges_report_solde_illimite: bool = True` | §11.1.3 |
| R2 | **Job d'acquisition paramétrable (D2c)** : seul le champ `taux_acquisition_jours_mois` existe | aucun job dans `app/` ; le motif `acquisition_mensuelle` existe déjà dans l'énumération | §11.1.1 |
| R3 | **Job de plafonnement de fin d'exercice**, motif `forclusion_report` à ajouter à `MotifMouvementConges` ; comportement final selon la DRH (surplus perdu ou indemnisé) | absent | §4.2.7 |
| R5 | **Webhooks sortants complets** : retries à délai croissant, consignation « non livré », journalisation de chaque tentative | `webhooks.py` : tentative unique ; `webhook_max_retries` défini mais non utilisé | §10 |
| R6 | **Routeur d'administration des `abonnements_webhook`**. À utiliser : `webhooks.creer_abonnement()` (chiffre le secret) | aucun routeur dans `main.py` | §3.1, §10 |
| R7 | **Anti-SSRF et HTTPS obligatoire** pour les URL de destination | aucune validation | §10 |
| R8 | **Webhook entrant Resend (signature Svix)** : suivi réel de livraison des e-mails | aucune trace de `svix` | §12, §14.2.2 |
| R10 | **Purge planifiée des jetons** consommés/expirés depuis plus de 90 jours | commentaire seulement | §4.4, §9.3 |

### P1 — Dette technique et cohérence

| # | Tâche | Détail |
|---|---|---|
| R11 | Stubs `TODO` de `services/extensions/bons_commande.py`, `communication.py`, `derogations.py` | La logique vit dans les routeurs ; extraire ou supprimer les stubs et documenter l'écart |
| R12 | `GET /api/v1/dashboard/` renvoie 501 | L'implémenter (§12) ou le retirer |
| R13 | `schemas/demande.py` : `TODO` | À trancher avec R12 |
| R14 | README : l'en-tête cite encore le CDC V2.4 et un « état actuel » périmé | Documentation |
| R15 | `docker-compose.yml` fait tourner l'application avec le propriétaire des tables | Dev seulement ; la production doit utiliser le rôle de `scripts/roles_postgresql.sql` |
| R16 | Journal d'audit non chaîné cryptographiquement ; consultation non journalisée | Amélioration, non exigée |
| R25 | **Modifier un congé ne renotifie pas le manager** | Il décide sur l'e-mail initial, avec les anciennes dates, sans être prévenu du changement |
| R26 | **Le décideur d'un rôle est le « premier compte actif »** (Direction financière, Juridique, DG, arbitre) sans règle d'ordre | Prévoir un compte par rôle, ou un routage explicite |
| R27 | Le **secret de chiffrement des webhooks** dérivé de `SECRET_KEY` : changer `SECRET_KEY` rend les secrets illisibles | Définir `WEBHOOK_ENCRYPTION_KEY` dédiée en production |

### P2 — Infrastructure et déploiement (rien n'est fait)

| # | Tâche | Bloque |
|---|---|---|
| D3 | Image conteneur PostgreSQL sur NubiStack (§14.1) | Tout déploiement |
| D3b | Raccorder **NubiS3** : le stockage est local derrière une interface (`stockage_fichiers.py`) | Pièces jointes et PDF |
| D4 | Sous-domaine d'envoi Resend (SPF/DKIM/MX) | Test réel manager + RH |
| D5 | Test d'envoi réel (`scripts/tester_resend_reel.py`) | Validation Resend |
| D6 | Projets NubieCloud dev / pilote / production, NubiBuild + NubiDeploy | Déploiement |
| D7 | NubiBackup avec test de restauration (§14.3) | Production |
| D8 | Rôle PostgreSQL restreint en environnement déployé (**valider que `mouvements_conges` est bien en ajout seul**) | Production |
| D9 | **Variables de production** : `COOKIE_SECURE=true` (HTTPS), `WEBHOOK_ENCRYPTION_KEY`, `SECRET_KEY`/`JWT_SECRET_KEY` forts | Production |
| D10 | **Reste du test navigateur** : expiration réelle de session, clic sur le lien d'un vrai e-mail → décision, Firefox et Safari (connexion + cookies déjà vérifiés dans Chromium) | Pilote |

### P3 — Gouvernance et validation métier

| # | Décision à obtenir | De qui |
|---|---|---|
| G1 | Dérogation de souveraineté Resend (données aux États-Unis, §14.2.3) | Direction |
| G2 | Taux d'acquisition exact des congés (D2c) | DRH / juridique |
| **G2bis** | **Règle de décompte d'un congé : jours calendaires ou lundi-vendredi ?** Puis régler `CONGES_EXCLURE_WEEKENDS` | DRH |
| G3 | Sort du surplus au-delà de 10 jours : perdu ou indemnisé (D2a) | DRH |
| G4 | Palier Resend payant avant le pilote | Budget |
| G5 | Destinataires de groupe et 4 rôles étendus : inclure ou reporter (§17.2) | Équipe |
| G6 | **Une dérogation supprime les niveaux suivants** (sur un achat : ni avis juridique ni signature DG) : est-ce voulu ? | Direction / Contrôle de gestion |

---

## 5. Séquencement recommandé

1. **Règles RH** : R1, puis R2 et R3 dès que G2/G3 sont connus (la mécanique paramétrable peut être codée avant la réponse DRH). Obtenir **G2bis** en parallèle.
2. **Webhooks** : R5, R6, R7 ensemble, un module cohérent avec ses tests.
3. **Suivi de livraison e-mail** : R8, après D4.
4. **Durcissement** : R10, R25, R26, R27.
5. **Nettoyage** : R11 à R14.
6. **Déploiement dev** : D3, D3b, D4, D6, D9.
7. **Pilote** : D5, D8, D10, G1, G4, test de délivrabilité, revue de sécurité applicative.
8. **Généralisation** : D7, formation, ouverture générale.

---

## 6. Comment rejouer les vérifications

```bash
# Backend (SQLite en mémoire) — variables minimales : SECRET_KEY, JWT_SECRET_KEY, DATABASE_URL, RESEND_API_KEY
pytest

# Concurrence réelle (base JETABLE : toutes les tables sont recréées)
WORKFLOWS_TEST_POSTGRES_URL=postgresql+asyncpg://user:mdp@localhost:5432/base_jetable pytest tests/postgres

# Chaîne complète sur PostgreSQL avec le rôle restreint
alembic upgrade head && alembic check
psql -f scripts/roles_postgresql.sql        # après avoir remplacé A_REMPLACER
DATABASE_URL=postgresql+asyncpg://workflows_app:...@host/base python3 scripts/verification/verifier_corrections_postgres.py

# Frontend
cd frontend && npm ci && npx vitest run && npx tsc --noEmit && npx next build
```

## 7. Hors périmètre initial (non planifié)

Tableau de bord analytique ; intégration comptable directe ; application mobile / notifications push ; chaînage cryptographique du journal d'audit (R16).


## Passe design « Impeccable » (05/10/2026)
- Contraste corrigé (bouton blanc/accent 3,3→4,9:1 ; liens accent ; gris clair 3→4,6:1 ; avertissement 3,3→5,4:1), focus visible, sélection, chiffres tabulaires, mouvement réduit, cibles tactiles 44 px (écrans tactiles).
- Pastille de marque (sidebar, connexion), largeurs de contenu alignées à gauche, état vide « Mes demandes » avec action.
- Vérifié : 222 tests frontend, tsc, next build, audit débordement 0, e2e discussion OK.

### Passe design n°2 (05/10/2026)
- Police Manrope auto-hébergée (@fontsource-variable/manrope, sans Google Fonts) ; champ fichier en français (`ChampFichier`, 5 formulaires) ; squelettes de chargement ; indice de défilement des tableaux ; marque sur les pages d'authentification et de décision.
- Régression détectée par l'audit navigateur puis corrigée : input masqué (sr-only) non contenu -> défilement horizontal de la page ; wrapper `relative`.
- Vérifié : 222 tests, tsc, build, audit 0, e2e 30 Mo 12/12, e2e discussion 3 processus à 390 px.

### Passe design n°3 (05/10/2026)
- Tableaux « en cartes » sous 768 px (Mes demandes, Notes de frais, Achats) : plus de colonnes Statut/Actions hors écran ; valeurs vides masquées.
- Thème sombre (prefers-color-scheme) via jetons ; jeton `--accent-text` pour liens ; pavé de signature gardé en papier clair. Contrastes mesurés ≥ 4,9:1.
- Limite assumée : sélecteur de date natif (format selon le navigateur).
- Vérifié : 222 tests, tsc, build, audit 0, e2e 30 Mo, e2e discussion x3.

### Vérification des circuits dérogation budgétaire (notes de frais) et achats (05/10/2026)
- `scripts/verification/circuits_budget_achats_e2e.py` : **77 contrôles** sur l'API réelle (comptes et service uniques par passage, approbateurs réels, jetons comme un clic e-mail) : standard, seuil 500 EUR -> Direction financière, dérogation par dépassement ou case cochée -> arbitre (Contrôleur de gestion), justification obligatoire, discussion pendant l'arbitrage, refus, annulation (liens caducs), usurpation (403), achat Juridique -> Direction générale signataire (signature obligatoire, bon de commande), achat en dérogation, budget consommé exact.
- `scripts/verification/interface/circuits_ui_e2e.py` : même parcours dans de vrais navigateurs (demandeur, arbitre, juriste, DG), à 1332 et 390 px.
- Corrigé : page de décision (approbateur) affichait « € » en dur pour toute devise ; onglet Budgets de l'administration idem (devise de référence lue côté serveur) ; e-mails de soumission : nom et service du demandeur désormais échappés (test de régression vérifié par mutation). Bloc budget : bordure gauche épaisse remplacée.
- Totaux : backend 445 passent / 3 ignorés ; frontend 224.

## Rattachement au manager par la DRH (05/10/2026)

Besoin : la DRH peut **changer le manager** d'un employé et **en attribuer un** à un compte qui n'en possède pas
(sans manager, une note de frais ou un congé est refusé : « Aucun manager rattaché »).

- **Backend** : `PATCH /api/v1/utilisateurs/{id}` (champ `manager_id`) et `POST /api/v1/utilisateurs/` ; logique dans
  `app/services/hierarchie.py`. Règles : manager existant, **actif**, de rôle **autre qu'« employé »**, pas l'employé
  lui-même, **aucune boucle** hiérarchique. Les demandes **en cours** (étapes en attente ou en discussion) chez l'ancien
  manager sont **transmises au nouveau** ; ses liens de décision sont révoqués, le nouveau manager reçoit de nouveaux
  liens par e-mail (relance automatique). Retirer le manager est refusé (409) tant qu'une demande l'attend. Audit :
  `compte_modifie` avec avant/après et la liste des demandes réaffectées. La réponse porte `demandes_reaffectees`.
- **Interface** (Administration → Comptes) : colonne Manager (« Aucun manager » signalé), actions « Attribuer un
  manager » / « Changer le manager », sélecteur « Manager (facultatif) » à la création, message de confirmation avec le
  nombre de demandes transmises, tableau en cartes sur téléphone.
- **Tests** : `tests/integration/test_hierarchie_manager.py` (13), 5 tests Vitest, `scripts/verification/interface/
  changement_manager_e2e.py` (3 navigateurs : DRH, employé, nouveau manager ; 1332 et 390 px).
- **Points ouverts** : un changement de rôle (ex. manager → employé) n'est pas contrôlé vis-à-vis de ses subordonnés ;
  les subordonnés d'un compte désactivé gardent ce manager (à traiter lors de la désactivation) ; le circuit achats n'utilise pas le manager.

## Installation et fichiers de déploiement (06/10/2026)

Audit du README d'installation, des deux Dockerfiles, de `docker-compose.yml` et de `.env.example` contre le code
réel. Le registre Docker est inaccessible depuis l'environnement de travail : **les images n'ont pas pu être
construites**. Chaque étape a donc été rejouée à la main (voir plus bas) ; un `docker compose up --build` réel reste
à faire une fois sur une machine avec accès au registre (D3-D10).

Écarts corrigés :
- **Pièces jointes perdues au redémarrage** : le dossier de stockage n'était sur aucun volume. Volume `pieces_jointes`
  (compose) et `VOLUME` + dossier appartenant à l'utilisateur applicatif (image).
- **Migrations manuelles** : `scripts/entrypoint.sh` + `RUN_MIGRATIONS` (vrai en compose, faux par défaut en production).
- **Images** : backend et frontend tournent désormais en utilisateur non privilégié, avec `HEALTHCHECK` ;
  `HOSTNAME=0.0.0.0` pour Next.js standalone (sinon injoignable via 127.0.0.1) ; `WEB_CONCURRENCY` ; compose attend
  `api` « healthy » avant `frontend`.
- **`.env.example`** : variables manquantes (`DEVISE_REFERENCE`, `COMPTABILITE_EMAIL`, `TAUX_TVA_BON_DE_COMMANDE`,
  `STOCKAGE_FICHIERS_DOSSIER`, `RUN_MIGRATIONS`) ; test `tests/unit/test_env_example.py` qui échoue si une variable de
  `Settings` manque ou si une variable inconnue y figure.
- **`seed_demo.py`** : non relançable, exercice 2026 codé en dur, mots de passe publics sans garde-fou. Relançable,
  exercice courant, un compte par rôle (achats et dérogations testables), enveloppe budgétaire, refus en production.
- **E-mails en développement** : clé Resend vide → le message (et ses liens) est écrit dans les logs au lieu d'échouer.
- **README** : bandeau d'état périmé, `DECISION_TOKEN_SECRET` (supprimée), « 11 tables », « HMR pour Vite »,
  `docker compose exec api pytest` (les tests ne sont pas dans l'image), compteurs de tests ; ajout d'une installation
  rapide, du développement sans Docker et d'une **liste de contrôle de mise en production**. `frontend/README.md` réécrit.
- **Tests** : la suite ne dépend plus du `.env` de l'installateur (clé Resend de test imposée dans `conftest.py`).

Vérifié par exécution : démarrage « comme l'image » sur une base vierge (entrypoint → 16 migrations → gunicorn 2
processus → `/health`), bootstrap du premier DRH, `seed_demo.py` deux fois, note de frais, note > 500 EUR et achat sur
cette instance (fichier écrit dans le dossier-volume), `npm ci` strict + build + serveur standalone avec les variables
de l'image (healthcheck, proxy → backend), 463 tests avec et sans `.env`.

Reste à faire : construire réellement les images ; reverse proxy ≥ 31 Mo ; sauvegarde du dossier des pièces jointes
avec la base ; stockage objet (NubiS3) toujours non raccordé.

## Vérification des e-mails des 3 circuits (06/10)
- Nouveau `tests/integration/test_emails_trois_circuits.py` (9 tests) : intercepte `resend.Emails.send`, suit les liens reçus (congés, notes de frais avec escalade > seuil et dérogation, achats juridique → signature), vérifie destinataires, motifs, relance, panne Resend.
- Corrigés : noms non échappés (HTML) dans les e-mails de soumission/régularisation de congés, DRH et demandeur ; nom mis en minuscules (`capitalize`) dans l'e-mail d'escalade ; libellé « Signer » (au lieu d'« Approuver ») pour l'étape Signataire.
- Limite : l'envoi réel via Resend n'a pas pu être testé (api.resend.com bloqué) ; à valider avec une vraie clé et un domaine vérifié.

## Refonte visuelle formulaires et titres (06/10)
- Formulaires centrés (nouvelle demande, régularisation, notes de frais, achats) ; fond plus clair avec halos ; titres en dégradé qui défile lentement (24 s, coupé en mouvement réduit) ; champs, cartes, boutons repris. Spec complète : `HANDOFF-refonte-visuelle.md`.
- Correctif (06/10, retour utilisateur) : fond derrière les pages assombri via un jeton dédié --page ; formulaires, cartes et champs gardent leurs couleurs d'origine.

## Bascule mode clair / sombre (06/10)
- Bouton rond (lune/soleil) en haut à droite du contenu (bureau), dans le bandeau (mobile) et sur la page de connexion. Choix mémorisé (localStorage), appliqué avant affichage (pas d'éclair), sans choix : suit le système. Composant `bouton-theme.tsx` (3 tests) ; e2e `scripts/verification/interface/bascule_theme_e2e.py` (21 contrôles OK).

## E-mails, notifications et fiche de confirmation d'absence (06/10)
- Gabarit commun `app/services/email_gabarit.py`, appliqué par `email_service.envoyer_email` : en-tête de marque, titre = sujet, cartes d'information, encarts (motif de refus), boutons d'action, pied de page ; styles en ligne uniquement (compatibilité Gmail/Outlook), aucun JavaScript ni image distante. Textes des 19 envois réécrits (ton chaleureux, emojis dans les sujets et le corps ; libellés de liens « Approuver / Refuser / Signer » inchangés pour rester exploitables). Invitation : rôle et service désormais échappés.
- Fiche de confirmation d'absence (PDF) refondue : bandeau de marque, pastille « congé approuvé », carte employé, période en 3 blocs (jours de la semaine, durée), détails, commentaire du demandeur, attestation, signature + tampon « VALIDÉ », pied de page avec référence. Sans emoji (polices de l'image de production).
- Tests : `tests/unit/test_email_gabarit.py` (5), 3 tests existants adaptés (sujets avec emoji, HTML habillé). Backend 477 réussis (3 ignorés).
- (06/10) Les e-mails habillés couvrent les trois circuits : vérifié sur les messages réels des tests (`EMAILS_DUMP=<dossier>` écrit chaque e-mail en .html). L'e-mail d'escalade (note de frais > seuil, achat → signature) comporte désormais une fiche récapitulative (demandeur, montant, catégorie/fournisseur, objet).
- (06/10) E-mails de compte (mot de passe oublié, invitation / réactivation) : même habillage, vérifiés par `tests/integration/test_emails_comptes.py` (2 tests : lien reçu utilisable pour définir le mot de passe, service échappé). Pied de page rendu générique (« Une question ? »).

## Pièces jointes dans les e-mails d'une demande (06/10)
- Source : documentation Resend « Attachments » (champs `filename` + `content` base64 ; 40 Mo maximum par e-mail, base64 compris). Plafond retenu : 25 Mo d'octets bruts par e-mail (~33 Mo encodés).
- `app/services/pieces_email.py` (nouveau) charge les pièces du dossier (jamais celles de la discussion), numérote les noms en double, joint dans la limite du plafond et NOMME les pièces omises (trop lourdes / illisibles) avec renvoi vers l'écran de décision. `email_service.envoyer_email` accepte `pieces_jointes`.
- Joint à : e-mail de soumission d'un achat (contrat), escalade (Direction financière, Direction générale), relance manuelle, rappels automatiques, synthèse envoyée à la comptabilité (reçus de la note validée).
- Congés et notes de frais : les pièces sont déposées APRÈS la soumission → chaque dépôt envoie à l'approbateur en attente un message « 📎 Pièce ajoutée » avec la pièce jointe (best-effort, un échec n'annule jamais le dépôt).
- Non joint volontairement : e-mails au demandeur (il possède déjà ses fichiers) et copie d'information à la DRH (minimisation : justificatif parfois médical ; la DRH garde l'accès en ligne). Ajoutable en une ligne si souhaité.
- Tests : `tests/integration/test_emails_pieces_jointes.py` (9). Backend 488 réussis (3 ignorés).
- Limites connues : un e-mail par pièce déposée (pas de regroupement) ; envoi réel Resend non testable ici (réseau bloqué), validé au niveau du payload.

## « Mes demandes » regroupe les trois types ; pages-formulaires allégées (07/10)
- `/mes-demandes` affiche désormais TOUTES les demandes initiées (congés, notes de frais, achats), la plus récente d'abord. Distinction de type : pastille neutre à icône (Congé / Note de frais / Achat) distincte de la pastille colorée de statut, plus onglets de filtre avec compteurs (Toutes · Congés · Notes de frais · Achats). `?type=` ouvre directement un onglet.
- `/notes-frais` et `/achats` ne contiennent plus que leur formulaire ; après soumission : lien « Suivre ma demande » puis redirection vers l'onglet concerné (annulée si l'on quitte la page ; pas de redirection si le dépôt du reçu a échoué, pour laisser lire l'avertissement). `/nouvelle-demande` inchangée.
- Code : `lib/demandes.ts` (types, fusion/tri, compteurs, libellés de statut : source unique), `components/ligne-demande.tsx` (ligne par type : pièces, actions, fiche, contrat, bon de commande, discussion). Chaque liste se charge indépendamment : la panne de l'une n'efface pas les deux autres. Colonne « Demande » bornée (nom très long : 2 lignes, texte complet au survol).
- Tests : Vitest 240 réussis (mes-demandes 26, tests de liste déplacés depuis notes-frais/achats, `statut-coherent` réécrit) ; e2e navigateur `scripts/verification/interface/mes_demandes_regroupees_e2e.py` (28 contrôles bureau + mobile) ; `circuits_ui_e2e.py` et `discussion_e2e.py` (3 types) repassent.
- Limite : pas de filtre par statut ni de pagination (comme avant) ; à ajouter si les volumes montent.

## Limite des fichiers portée à 40 Mo (07/10)
- `TAILLE_MAX_MO = 40` (`app/services/stockage_fichiers.py`) et `TAILLE_MAX_FICHIER_MO = 40` (`frontend/src/lib/fichiers.ts`) : contrat des achats, reçus, justificatifs, compléments, pièces de la discussion. Messages, texte de la page Achats, README et guide alignés.
- Tests : valeurs littérales à 40 Mo (backend : unitaires + 3 routes ; frontend : `fichiers.test.ts`, discussion, notes de frais) ; e2e `fichiers_40mo_e2e.py` (remplace `fichiers_30mo_e2e.py`) 13/13 via le proxy Next.js et de vrais formulaires ; discussion avec une pièce de 38 Mo OK.
- **Déploiement** : un reverse proxy devant l'application doit accepter au moins **41 Mo** (nginx : `client_max_body_size 41m;`).
- **E-mails** : Resend limite un e-mail à 40 Mo en base64 ; le plafond de pièces jointes reste 25 Mo bruts (`pieces_email.PLAFOND_OCTETS`). Un fichier de plus de 25 Mo (jusqu'à 40 Mo) est donc accepté au dépôt, mais NOMMÉ dans l'e-mail et consultable dans l'écran de décision, jamais joint (test dédié).
- Test local de l'interface en production sur HTTP : démarrer avec `COOKIE_SECURE=false` (sinon les cookies de session ne sont pas renvoyés).

## Test de bout en bout des circuits : e-mails + discussion + dérogation (07/10)
- `tests/integration/test_circuits_emails_discussion.py` (10 parcours) : chaque demande est déroulée de la soumission à la clôture à travers l'API, e-mails interceptés au niveau Resend. Vérifié à chaque étape : qui reçoit quoi (demandeur / approbateur / comptabilité), liens de décision extraits des e-mails ET des messages de discussion puis réellement utilisés, gel de la décision pendant la discussion (409), contrôle d'accès de la discussion (403 pour un tiers ou l'ancien approbateur), reprise, effets (budget débité, BC attribué) et absence d'e-mails pour les étapes non concernées.
- Parcours couverts : achat juridique → DG avec discussion aux deux niveaux (+ contenu du bon de commande PDF) ; refus du juridique après discussion ; note de frais > seuil manager → Direction financière avec discussion puis comptabilité ; refus de la Direction financière (pas de comptabilité) ; congés avec discussion ; dérogation achat (acceptée, refusée) ; dérogation note de frais par dépassement automatique (un seul niveau malgré un montant > seuil) ; repli sur la DG sans Contrôleur de gestion ; dérogation sans aucun arbitre (refus propre, aucun e-mail).
- **Défauts trouvés et corrigés** (achat en dérogation uniquement) : (1) l'e-mail d'approbation au demandeur affirmait « l'avis juridique et la validation de la Direction générale sont obtenus » alors que ces étapes sont contournées ; (2) le bon de commande imprimait l'arbitre comme « Service juridique — Avis favorable » et « Signataire introuvable ». Désormais : e-mail « acceptée en arbitrage exceptionnel (dérogation) » et bon de commande avec bloc « Arbitrage exceptionnel (dérogation) » (arbitre, date, motif) et certificat adapté (`documents.generer_bon_de_commande(arbitre=…)`, `decisions.py`, `achats.py`).
- Backend : 499 réussis (3 ignorés).
- Limites connues : la justification d'acceptation de l'arbitre n'est conservée que dans le journal d'audit (pas imprimée sur le bon) ; en dérogation aucune signature graphique n'est capturée ; le garde-fou « un approbateur ne valide pas sa propre demande » reste à décider (options récusation / refus à la soumission / autorisation tracée).

## Signature graphique de l'achat testée à fond ; dérogation des notes de frais → Direction financière seule (07/10)
- **Décision** : une note de frais en dérogation (dépassement budgétaire ou motif du demandeur) est arbitrée par la **Direction financière seule** — ni Contrôleur de gestion, ni repli sur la Direction générale ; sans compte Direction financière actif, la soumission échoue (422, message explicite). **Achats inchangés** : Contrôleur de gestion, repli Direction générale. Code : `routing_engine.determiner_etape_derogation` (branche par processus). Tests adaptés (`test_derogations_api`, `test_conformite_cdc`, `test_emails_trois_circuits`, `test_circuits_emails_discussion`) + 2 nouveaux (aucun autre arbitre même si DG et Contrôleur existent ; la DF est choisie malgré un Contrôleur). README et guide mis à jour.
- **Tests de la signature** (`tests/integration/test_signature_graphique.py`, 7) : tracé stocké octet pour octet ; **image réellement présente dans le PDF** (extraction `pdfimages`, 360×140, avec un trait) ; deux signatures différentes → deux bons différents ; seule la DG attendue peut signer (403 pour juriste/demandeur, 401 sans session), une seule fois ; refus de la DG sans signature ni bon ; achat jamais « signé » sans signature valide ; 10 signatures invalides refusées sans brûler le lien (absente, base64 invalide, texte, PNG tronqué ou coupé, JPEG déguisé, transparent, blanc, gigantesque, trop lourd), le même lien fonctionnant ensuite avec une vraie signature. `tests/signature_factory.py` fabrique de vrais tracés.
- **Navigateur** (`scripts/verification/interface/signature_achat_e2e.py`, 18 contrôles à 1332 / 390 / 320 px) : « Signer » bloqué sans tracé, tracé à la souris réelle, alignement pointeur/encre, « Effacer », re-tracé, signature, téléchargement du bon par le demandeur et comparaison de la quantité d'encre canvas ↔ PDF (identique au pixel près).
- **Défauts trouvés et corrigés** : (1) le serveur acceptait n'importe quels octets comme « signature » (PNG tronqué, texte, image vide) et le bon affichait « Signé électroniquement » sans aucun tracé (WeasyPrint ignorait l'image en silence) → `app/services/signature.py` : PNG complet et lisible, ≤ 1 Mo, ≤ 4000 px, au moins un pixel visible ; contrôle de la fin de fichier explicite car WeasyPrint active globalement `LOAD_TRUNCATED_IMAGES` ; (2) **sur téléphone** le pad ne ramenait pas les coordonnées à l'échelle du canvas (affiché à 308 px au lieu de 360) : tracé décalé et écrasé, moitié droite perdue → conversion pointeur → coordonnées internes (`signature-pad.tsx`, 4 tests Vitest dont un qui échoue sans le correctif).
- Revalidés en réel : `circuits_ui_e2e.py` (arbitre de la note = Direction financière) et `circuits_budget_achats_e2e.py` sans échec.
- Totaux : backend 508 réussis (3 ignorés), frontend 244 réussis.
- Limites : le contrôle « non vide » n'empêche pas un simple point. (Le ratio de pixels des écrans haute densité est traité : voir la section suivante.)

## Pad de signature net sur écrans haute densité (07/10)
- Constat : le canvas faisait toujours 360 × 140 px internes ; sur un écran 2x ou 3x (iPhone, Retina) le navigateur l'agrandissait : trait flou, bords en escalier, PNG plus grossier dans le bon de commande.
- Correction (`frontend/src/components/signature-pad.tsx`) : résolution interne = 360 × 140 × densité de l'écran (`devicePixelRatio`, bornée à 3x → 1080 × 420 au maximum, valeurs invalides = 1x), épaisseur du trait proportionnelle (2 px CSS apparents), zone affichée inchangée ; la conversion pointeur → pixels internes de la correction précédente absorbe l'échelle. Le serveur accepte déjà ces tailles (≤ 4000 px, ≤ 1 Mo ; un tracé 3x pèse quelques Ko).
- Tests : Vitest 10 (dont densités 1, 2, 3, 5 → 360, 720, 1080, 1080 ; conversion + épaisseur à 2x ; densité invalide) ; e2e `signature_achat_e2e.py` avec `UI_DPR` : 1332 px 1x et 2x, 390 px 1x et 2x, 320 px 3x, tous sans échec — le PDF embarque l'image à la résolution du pad (720 × 280 à 2x) avec exactement la même quantité d'encre que le canvas.
- Totaux : backend 508 réussis (3 ignorés), frontend 250 réussis.

## Conformité des Dockerfile avec le code (07/10)
- **Périmètre audité** : `Dockerfile` (backend), `frontend/Dockerfile`, `frontend/Dockerfile.dev`, `docker-compose.yml`, `.dockerignore` (×2), `scripts/entrypoint.sh`, `requirements.txt` — recoupés avec le code (imports, chemins, ports, variables, `/health`, stockage des pièces jointes, `output: "standalone"`).
- **Conforme** : image multi-étapes, utilisateur non root (uid 10001), `VOLUME` = dossier de stockage par défaut du code (`/var/lib/workflows/pieces-jointes`) et même volume dans compose, port 8000 / `/health` / `app.main:app` + UvicornWorker, migrations via `RUN_MIGRATIONS`, variables de compose (`DATABASE_URL`, `CORS_ALLOW_ORIGINS`, `FRONTEND_BASE_URL`, `API_BASE_URL`) toutes connues du code, frontend standalone (`server.js`, `.next/static`, `HOSTNAME=0.0.0.0`).
- **Écarts trouvés et corrigés** : (1) **polices absentes** de l'image `python:3.12-slim` → PDF (bon de commande, fiche d'absence) au texte non fiable : ajout de `fonts-liberation`, `fonts-dejavu-core`, `fontconfig`, `libfontconfig1` ; (2) **bibliothèques non déclarées** nécessaires à WeasyPrint 63 : `libpangoft2-1.0-0`, `libharfbuzz0b`, `libharfbuzz-subset0` ; (3) **bibliothèques inutiles retirées** de l'image finale (`libcairo2`, `libpangocairo-1.0-0`, `libgdk-pixbuf-2.0-0` — non utilisées par WeasyPrint 63) → image plus petite, moins de surface de vulnérabilités ; (4) **Pillow importé par `app/services/signature.py` mais absent de `requirements.txt`** (présent seulement par dépendance transitive) → déclaré ; (5) `scripts/verification` (scripts Playwright de dev) exclu de l'image ; (6) `frontend/.dockerignore` : motifs `*.test.ts(x)` remplacés par `**/*.test.ts(x)` (sinon seuls les fichiers à la racine étaient exclus).
- **Tests** : `tests/unit/test_conformite_docker.py` (9 tests, statiques, sans démon Docker) : tout import tiers de `app/` déclaré dans requirements ; paquets runtime WeasyPrint + polices présents, paquets inutiles absents ; chemins `COPY` existants ; VOLUME = stockage par défaut ; port/healthcheck/commande = application ; variables compose connues ; frontend standalone cohérent.
- **Simulation de l'image frontend** (contexte « Docker-like » sans node_modules/.next/.env/tests) : build OK, mise en page finale assemblée, `node server.js` avec l'environnement du Dockerfile : `/login` 200, chunk statique 200, proxy `/api/backend/health` 200 une fois le backend lancé (le 500 précédent venait uniquement du backend arrêté).
- **Build réel validé (07/10, par l'utilisateur)** : `docker build` exécuté sur sa machine après ces corrections — les builds (backend et frontend) réussissent parfaitement. Plus de réserve sur les noms de paquets Debian (trixie).
- Totaux : backend 517 réussis (3 ignorés), frontend 250 réussis.

## Build Docker simulé « pour de vrai » (07/10)
- **Méthode** : `dockerd` local démarré (stockage vfs) ; Docker Hub et les dépôts Debian étant injoignables, deux images de base locales jouent `python:3.12-slim` et `node:22-alpine` (rootfs Ubuntu 24.04 par debootstrap + Python 3.12 / Node 22, utilisateur `node` uid 1000). Les deux Dockerfile sont construits **tels quels** (`scripts/verification/simuler_build_docker.sh`).
- **Résultats** : `docker build` backend OK (1 min 17, multi-étapes, apt + pip, Pillow 12 / WeasyPrint 63.1 installés) ; `docker build` frontend OK (59 s, `npm ci` + `next build` standalone). Images : backend 664 Mo, frontend 636 Mo.
- **Conteneur backend** : utilisateur `appuser` (uid 10001), volume `pieces-jointes` en écriture, 20 polices disponibles, PDF WeasyPrint généré dans le conteneur, `alembic upgrade head` via `RUN_MIGRATIONS`, gunicorn + 2 workers Uvicorn, planificateur démarré, `/health` 200 et **healthcheck « healthy »**.
- **Conteneur frontend** : utilisateur `node`, `/login` 200, proxy `/api/backend/health` 200 vers le conteneur backend.
- **E2E à travers les conteneurs** : `circuits_budget_achats_e2e.py` (notes de frais, achats, dérogation, discussion, bon de commande PDF) : **aucun échec** ; `signature_achat_e2e.py` (Playwright sur l'interface du conteneur frontend, vraie signature, PDF téléchargé, encre canvas = PDF 933/933) : **aucun échec**.
- **Limites honnêtes** : Ubuntu noble ≠ Debian trixie (le build réel de l'utilisateur, déjà réussi, couvre cet écart) ; glibc ≠ musl (Alpine) côté Node ; healthcheck frontend testé avec `PORT=3100` donc resté « starting » (il interroge le port 3000 par défaut — normal).

## Stockage S3 (NubieS3 / Backblaze B2) raccordé (08/10)
- **Besoin** : jusqu'ici les pièces jointes (contrats, justificatifs, fichiers de discussion, images de signature) n'existaient que sur un disque local du conteneur — volume Docker obligatoire, une seule instance possible. Le bucket NubieS3 `workflow-stockage` (endpoint `https://s3.eu-central-003.backblazeb2.com`, région `eu-central-003`) est désormais utilisable.
- **Fonctionnement** (`app/services/stockage_fichiers.py`) : S3 est actif si les 4 variables `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` sont renseignées ; sinon repli sur le dossier local (développement, tests). **Configuration partielle = l'API refuse de démarrer** (jamais d'écriture silencieuse sur un disque éphémère). Nouvelles variables optionnelles : `S3_REGION` (déduite de l'endpoint si vide) et `S3_PREFIX` (défaut `workflows/`, utile car le bucket est partagé par l'organisation). Bucket PRIVÉ : les téléchargements passent par l'API authentifiée. La clé stockée en base est inchangée (opaque) : aucun changement de schéma, aucune migration Alembic. Client boto3 (signature v4, adressage par chemin, 5 tentatives, sommes de contrôle « when_required » pour la compatibilité Backblaze). Les routes appellent le stockage via `asyncio.to_thread` (l'appel réseau ne bloque plus la boucle asynchrone).
- **Exploitation** : `python -m scripts.verifier_stockage` (écrit, relit, supprime un objet de test — à lancer après avoir saisi les clés) ; `python -m scripts.migrer_fichiers_vers_s3 [--dry-run] [--verifier-base]` (copie les fichiers locaux existants avec les mêmes clés, ne supprime jamais le local, relançable, et contrôle que chaque référence de la base existe dans le bucket). Le démarrage journalise le mode actif (sans secret).
- **Mise en production** : (1) NubieS3 > bucket > Access keys > « Nouvelle access key » (le secret n'est affiché qu'une fois) ; (2) renseigner les 4 variables (+ région/préfixe) dans le `.env` ; (3) `python -m scripts.verifier_stockage` ; (4) s'il existe déjà des fichiers locaux : `migrer_fichiers_vers_s3 --dry-run` puis sans `--dry-run` puis `--verifier-base` ; (5) le volume `pieces-jointes` n'est alors plus nécessaire. La version en production (congés seuls) n'a aucun fichier à migrer.
- **Tests** : `tests/unit/test_stockage_s3.py` (13 : aller-retour, clé opaque + préfixe, absent → FileNotFoundError, suppression idempotente, 40 Mo, région, bout en bout, mauvais bucket → erreur claire, configuration partielle refusée, repli disque, aucun secret dans les journaux, scripts de migration/vérification) sur un VRAI serveur S3 simulé (moto en HTTP, endpoint personnalisé comme NubieS3) ; `tests/integration/test_stockage_s3_circuit.py` (achat complet : contrat → bucket, téléchargement, signature de la DG stockée à l'identique, bon de commande PDF avec la signature relue depuis S3 ; fichier de discussion) ; conformité Docker étendue (variables S3 documentées, boto3 déclaré, scripts dans l'image).
- **Image Docker réelle simulée** (dockerd local) : build OK avec boto3 ; dans le conteneur : `verifier_stockage` OK, configuration partielle refusée, migration `--dry-run` OK ; API en conteneur avec S3 + e2e `circuits_budget_achats_e2e.py` : aucun échec, objets présents dans le bucket, 0 fichier sur le disque du conteneur ; contrôle base → bucket sur la base PostgreSQL réelle opérationnel (détecte bien les 170 références absentes d'un bucket vide).
- **Limites** : non testé contre le VRAI bucket NubieS3 (réseau restreint ici) — d'où `scripts.verifier_stockage` à lancer une fois chez vous ; un bug du client boto3 propre à Backblaze reste possible mais la configuration anticipe le cas connu (sommes de contrôle). Les fichiers sont lus en entier en mémoire (≤ 40 Mo) comme avant.
- Totaux : backend 533 réussis (3 ignorés).

### Simulation « 4 variables S3 renseignées → tout part dans le bucket » (08/10)
API réelle (uvicorn) + PostgreSQL réel + serveur S3 simulé (endpoint personnalisé), avec `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` (+ région) et un dossier local dédié surveillé. Résultat : démarrage journalisé « Stockage des pieces jointes : S3 », e2e `circuits_budget_achats_e2e.py` sans échec, 6 objets dans le bucket (tous sous `workflows/`), **0 fichier sur le disque local**. 20 tests de stockage OK. Correction : commentaire obsolète de `stockage_fichiers_dossier` (config.py) mis à jour. Reste : test contre le vrai bucket (`python -m scripts.verifier_stockage`).

### Références internes retirées des textes visibles (08/10)
Signalé : « (section 9 du CDC technique) » apparaissait dans le certificat de validation du bon de commande PDF. Retiré des 2 variantes (circuit standard et dérogation), ainsi que : descriptions Swagger de l'API achats (« CDC technique 4.1 », « section 3 du CDC fonctionnel »), message d'erreur du journal d'audit (« CDC 2.4, technique 14.3 »), et mention « Option B du CDC technique » sur l'écran de confirmation de décision. Les commentaires/docstrings (développeurs) gardent leurs renvois. Garde-fou : `tests/unit/test_aucune_reference_cdc_visible.py` (analyse AST des chaînes non-docstring de `app/` + textes JSX du frontend ; échoue si « CDC », « section N », « §N », « R\d+ », « Option A/B » y réapparaît).
