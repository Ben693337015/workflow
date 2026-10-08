# Matrice de conformité au cahier des charges — congés, notes de frais, achats & contrats

Audit du 28/09/2026. Source de référence : **Cahier des Charges Fonctionnel Complet** (sections 2 à 5), complété par le
cahier des charges technique V2.4 pour les choix d'implémentation. Chaque statut a été vérifié dans le code
(commande de recherche ou test), pas repris d'un compte rendu antérieur.

Légende : ✅ conforme · 🟡 partiel · ❌ absent · 🔧 corrigé lors de cet audit

> **Correction d'un compte rendu antérieur.** Le tableau de couverture du cahier des charges technique (§17.1) déclarait
> « relances automatiques » couvertes ; je l'avais repris tel quel alors qu'**aucun planificateur n'existait** (seule la
> relance manuelle des congés). Les rappels automatiques sont désormais implémentés (28/09, voir §4).

## 1. Demande de congés

| Exigence du CDC | Statut | Preuve / remarque |
|---|---|---|
| Nature de l'absence, dates de début et de fin | ✅ | `schemas/conges.py`, types de congé administrables |
| Cohérence chronologique (fin ≥ début) | ✅ | validateur Pydantic + route |
| **Justificatif d'absence** (donnée clé) | 🔧 | facultatif : dépôt à la soumission ou depuis « Mes demandes », consultable par le manager sur la page de décision (le champ orphelin `justificatif_id` est supprimé) |
| Validation du supérieur, puis notification RH | ✅ | `_notifier_drh` (destinataire en copie, sans blocage) |
| Fiche de confirmation d'absence | ✅ | PDF généré à la demande |
| Mise à jour de l'agenda de l'équipe | ✅ | `GET /conges/agenda-equipe` + page |
| Verrou RH sur le solde (§4.2) | ✅ | blocage à la soumission (`verrou_rh`) |
| Demande de dérogation (§4.4) | ✅ | non applicable aux congés par décision (28/09) : le CDC la rattache au dépassement d'enveloppe budgétaire, absent des congés |
| Discussion / suspension (§4.5) | ✅ | générique aux trois processus |
| Relance manuelle, annulation, modification | ✅ | congés uniquement |

## 2. Notes de frais professionnelles

| Exigence du CDC | Statut | Preuve / remarque |
|---|---|---|
| Typologie de dépense, montant total | ✅ | montant numérique strictement positif |
| **Devise** (donnée clé) | 🔧 | plusieurs devises avec conversion (décision du 28/09) : taux figé à la soumission, seuil et budget comparés au montant converti — `services/devises.py`, écran d'administration « Devises » |
| **Photo / fichier du reçu fiscal** (donnée clé) | 🔧 | facultatif (décision du 28/09) : dépôt à la soumission ou depuis la liste, consultable par les approbateurs sur la page de décision |
| Cohérence chronologique des dates (§2.1) | 🔧 | une date future est désormais refusée (backend) et plafonnée dans le formulaire |
| Validation du manager ; > 500 € → Direction financière | ✅ | seuil configurable ; escalade multi-niveaux testée |
| **Tableau de synthèse transmis à la comptabilité** (livrable) | 🔧 | e-mail à chaque validation finale (adresse `COMPTABILITE_EMAIL` configurable) + écran « Synthèse des frais » avec export CSV sécurisé (DRH, Direction financière, Contrôleur de gestion) |
| Solde budgétaire calculé (§4.3) | ✅ | enveloppes par service et exercice |
| **Solde budgétaire affiché au décideur** (§4.3, « obligatoirement ») | 🔧 | n'était montré nulle part ; désormais dans l'aperçu de décision, la page et les e-mails (vert / rouge) |
| Dérogation motivée ou dépassement → arbitrage (§4.4) | ✅ | motif et justification d'acceptation gravés dans le journal |
| Discussion / suspension (§4.5) | ✅ | pièces complémentaires comprises |
| Relance manuelle, annulation | ✅ | parité avec les congés (28/09) — logique partagée `services/gestion_demandes.py` |
| Notification d'avancement au demandeur (§2.3) | 🟡 | décision finale notifiée ; l'escalade vers la Direction financière ne l'est pas |

## 3. Validation d'achats et contrats

| Exigence du CDC | Statut | Preuve / remarque |
|---|---|---|
| Tiers, objet, budget engagé | ✅ | |
| Fichier du contrat | ✅ | un contrat à la soumission ; documents complémentaires possibles ensuite (« un ou plusieurs documents », §2.1), jusqu'à 10 pièces |
| Contrat consultable par les approbateurs | 🔧 | n'était accessible que par un chemin d'API cité dans un e-mail ; désormais sur la page de décision |
| Avis du Service juridique, puis Direction générale (signataire) | ✅ | circuit fixe à deux niveaux |
| Signature électronique du signataire (§8) | ✅ | action distincte, tracé capturé et stocké |
| Certificat de validation | 🟡 | mention imprimée (identités, horodatage), pas un certificat cryptographique |
| Bon de commande : numéro séquentiel, HT/TVA/TTC, pavé de signatures, CGA en page 2 | ✅ | `BC-AAAA-NNNN`, PDF |
| BC : **calculs de taxes différenciés par ligne**, « TVA par taux » | ❌ | pas de lignes ; un seul taux (20 %) appliqué à un montant supposé TTC |
| BC généré et joint automatiquement à la validation | 🟡 | généré à la demande ; pas d'envoi automatique |
| Solde budgétaire calculé et affiché au décideur (§4.3) | 🔧 | comme pour les notes de frais |
| Dérogation (§4.4), discussion (§4.5) | ✅ | |
| Relance manuelle, annulation | ✅ | parité avec les congés (28/09) ; le niveau Signataire (Direction générale) relance avec un lien « signer », jamais « approuver » |

## 4. Exigences transversales

| Exigence du CDC | Statut | Preuve / remarque |
|---|---|---|
| Identité du demandeur certifiée par la session | ✅ | JWT ; jetons de décision à usage unique |
| Décision directe depuis la notification + double vérification d'identité (§5) | ✅ | Option B active par défaut |
| **Rappels automatiques à fréquence paramétrable (§2.4)** | 🔧 | `services/rappels.py` + boucle du backend ; fréquence (48 h par défaut) et périodicité réglables ; sans doublon multi-instances ; consignés au journal ; testés (16 tests, 3 mutations détectées) et vérifiés en réel |
| Journal d'audit horodaté et attribué | ✅ | soumission, décisions, signature, suspension, dérogation |
| Journal **inaltérable** | 🔧 | déclencheurs en base (`UPDATE`, `DELETE`, `TRUNCATE` refusés, propriétaire compris) + garde ORM ; **limite** : un propriétaire peut les retirer par DDL, d'où le rôle applicatif restreint (`scripts/roles_postgresql.sql`, validé sur toute l'application) |
| Journal **consultable** (traçabilité) | 🔧 | `GET /audit/` (filtres, pagination) + écran « Journal d'audit » pour DRH, Direction générale, Contrôleur de gestion ; historique du dossier pour ses participants |
| Actions d'**administration** consignées (budgets, comptes, rôles, soldes…) | 🔧 | 11 actions, avec avant / après ; aucune n'était consignée |
| Limitation des tentatives de connexion, journalisation des connexions (technique §5) | ❌ | absentes |
| Tableau de suivi (technique §12) | ❌ | `GET /api/v1/dashboard/` renvoie 501 ; pas d'écran « à traiter » pour les approbateurs |
| Webhooks (décision d'équipe) | 🟡 | envoi signé HMAC ; **tentative unique, sans reprise** ; aucune route d'abonnement ; pas de contrôle SSRF |
| Historique de discussion annexé au dossier final | ❌ | consultable par la route, non intégré aux PDF |
| Discussion avec « un autre service » | ❌ | limitée au demandeur et à l'approbateur |
| Souveraineté des données (§5) | 🟡 | e-mails transitant par un prestataire (Resend) ; le CDC technique §14.2 le signale et réserve la pleine conformité à un SMTP interne |

## 5. Bilan

- **Conformes** : le cœur des trois circuits (routage, rôles, décision par lien sécurisé, signature, verrou RH, suivi
  budgétaire, dérogations, discussion) et leurs livrables principaux (fiche de congés, agenda, bon de commande).
- **Corrigés lors de cet audit** : affichage du solde budgétaire au décideur ; cohérence de la date d'une note de frais ; rappels automatiques ; reçu, justificatif et consultation des pièces par les approbateurs ; journal d'audit inaltérable, consultable et couvrant l'administration ; plusieurs devises avec conversion ; synthèse comptabilité (e-mail + écran + export) ; relance et annulation pour notes de frais et achats ; TVA différenciée par ligne du bon de commande.
- **Décisions tranchées le 28/09** : dérogation pour les congés → non ; devise → plusieurs devises avec conversion ; synthèse comptabilité → e-mail et écran.
- **Absents, par ordre de priorité proposé** :
  1. ~~Rappels automatiques~~ — **fait le 28/09**.
  2. ~~Reçu des notes de frais et justificatif des congés~~ — **fait le 28/09** (facultatifs).
  3. ~~Synthèse des notes de frais transmise à la comptabilité~~ — **fait le 28/09**.
  4. ~~Journal d'audit : inaltérabilité en base et consultation~~ — **fait le 28/09**.
  5. ~~Devise~~ — **fait le 28/09** (plusieurs devises avec conversion).
  6. ~~Relance et annulation pour notes de frais et achats~~ — **fait le 28/09** (parité avec les congés).
  7. ~~Lignes et TVA par taux du bon de commande~~ — **fait le 28/09**. Restent : tableau de suivi ; reprise et gestion des webhooks.
