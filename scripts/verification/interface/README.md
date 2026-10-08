# Vérification de l'interface dans un vrai navigateur (Chromium)

Les tests Vitest (jsdom) ne calculent **aucune mise en page** : ils ne peuvent pas voir un tableau coupé, une barre
latérale qui remonte avec la page, ou un texte qui déborde. Ces scripts le mesurent dans un vrai navigateur.

## Prérequis
- Backend et frontend lancés (`uvicorn app.main:app`, `next dev` ou `next start`), PostgreSQL migré.
- `pip install playwright httpx` puis `python3 -m playwright install chromium`.
- Les comptes `verif-employe|manager|drh-<suffixe>@example.com` créés par `../verifier_corrections_postgres.py`
  (mot de passe `MotDePasseVerif123!`). Variables : `UI_SUFFIXE` (obligatoire), `UI_BASE` (défaut
  `http://localhost:3000`), `UI_SORTIE` (dossier des captures et rapports, défaut `/tmp`).

## Utilisation
```bash
export UI_SUFFIXE=0c1081
python3 seed.py && python3 seed2.py && python3 seed3.py         # données, dont des textes volontairement extrêmes
python3 audit.py rapport.json && python3 resume.py rapport.json  # 4 largeurs d'écran x toutes les pages
python3 barre_laterale_fixe.py                                   # la barre latérale reste fixe, seul <main> défile
python3 fenetre_basse.py                                         # fenêtre très basse + tiroir mobile
PYTHONPATH=../../.. python3 tokens.py && python3 audit_pages_donnees.py   # page de décision et discussion
PYTHONPATH=../../.. UI_LARGEUR=1332|390|320 UI_DPR=1|2|3 python3 signature_achat_e2e.py                    # signature graphique de la DG : tracé réel, effacer, bon de commande PDF (encre canvas = encre du PDF)
python3 fichiers_40mo_e2e.py                                      # limite de 40 Mo : proxy Next.js + formulaires réels, fichiers de 12, 30+1, 39, 40 et 41 Mo
UI_PROCESSUS=conges|notes_frais|achats UI_LARGEUR=1332|390 UI_TAILLE_MO=25 PYTHONPATH=../../.. python3 discussion_e2e.py
#   discussion demandeur <-> approbateur, 2 navigateurs, de la suspension à l'approbation (l'approbateur réel est lu en base ;
#   pour les achats c'est le Service juridique : son compte doit avoir le mot de passe de test)
```

## Ce que l'audit détecte
Texte coupé par un conteneur (`overflow: hidden`), texte tronqué sans « … », texte qui dépasse de son bloc,
élément hors de l'écran sans zone de défilement, défilement horizontal de la page. Les défilements internes d'un
tableau (volontaires sur petit écran) sont listés à part.

## Résultat de référence (30/09/2026)
Avant correction : 156 signalements de coupure/débordement. Après : **0**, à 1332, 1024, 768 et 390 px.

```bash
PYTHONPATH=../../.. python3 circuits_ui_e2e.py     # note de frais en dérogation + achat (juridique puis DG signataire), 4 navigateurs ; UI_LARGEUR=390 pour mobile
# (côté API : ../circuits_budget_achats_e2e.py, 77 contrôles)
```

```bash
PYTHONPATH=../../.. python3 changement_manager_e2e.py   # la DRH attribue puis change le manager d'un employe ; demande en cours transmise ; boucle refusee. UI_LARGEUR=390 pour mobile
```

```bash
python3 mes_demandes_regroupees_e2e.py   # « Mes demandes » : 3 types regroupés, onglets/compteurs, pages-formulaires sans liste, redirection après soumission (bureau + 390 px)
```
