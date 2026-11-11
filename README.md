# EduGest : plateforme SaaS multi-établissements (ERP éducatif)

Chaque personne crée elle-même son compte et son établissement (comme un compte Google) : aucun administrateur
ne crée les comptes à sa place. Ensuite, l'administrateur de l'établissement **invite** son équipe par e-mail et
chacun choisit son propre mot de passe. Écoles classiques (niveaux et classes) et universités (facultés, programmes).
Django 4.2 LTS · MySQL (utf8mb4) via **PyMySQL** · **python-decouple** · Bootstrap 5 (embarqué, sans CDN).

## Fonctionnement SaaS

| Besoin | Réalisation |
|--------|-------------|
| Inscription libre | `/inscription/` : compte + établissement créés en une étape, essai gratuit de 30 jours |
| Connexion | par adresse e-mail ; mot de passe oublié par e-mail ; confirmation d'adresse par lien |
| Protection de connexion | limitation temporaire après plusieurs tentatives échouées |
| Espaces isolés (tenants) | `etablissement` sur chaque entité, filtrage côté serveur, un utilisateur peut appartenir à plusieurs espaces et en créer d'autres |
| Équipe | invitation par e-mail liée à l'adresse invitée (7 jours), rôles par établissement, désactivation, dernier administrateur protégé |
| Démarrage rapide | année, périodes, niveaux et classes en une seule étape + liste « Premiers pas » |
| Paramètres | identité, règles de notation, vocabulaire institutionnel et durée de conservation des dossiers |
| Abonnements | plans Essai / Standard / Premium, quotas (apprenants, personnel), blocage si suspendu ou essai terminé |
| Console plateforme | `/plateforme/` (superutilisateur) : établissements, plans, suspension et réactivation |
| Pages publiques | accueil, tarifs, connexion, inscription, candidature en ligne (`/admissions/`) |

Les paiements en ligne ne sont pas inclus : le plan d'un établissement est modifié depuis la console plateforme.
Les événements de paiement et les mesures quotidiennes d'usage sont conservés sans connecter de prestataire.
`python manage.py capturer_usage_abonnements` permet de prendre une mesure ponctuelle ; planifier cette commande
quotidiennement pour alimenter l'historique. Aucun webhook de paiement n'est activé.
Les candidatures peuvent être déposées sans compte ; la direction les examine dans « Candidatures ». Leur
acceptation crée le dossier et l'inscription validée, puis invite le parent à créer son compte. Le formulaire
enregistre le consentement au traitement des données. Les candidatures refusées et leurs coordonnées doivent être
traitées selon la politique de conservation de l'établissement.

Les importations sont disponibles sous `/importations/` pour les rôles autorisés : CSV UTF-8 ou Excel (`.xlsx`),
aperçu avant validation, limites de taille et de lignes, inscription éventuelle dans l'année active et invitation du
personnel par le mécanisme de création de compte existant. Les aperçus contenant des données personnelles expirent
après 24 heures ; planifier `python manage.py nettoyer_apercus_importation` pour purger régulièrement ces données.

Le portail `/rgpd/mes-donnees/` permet aux apprenants et responsables liés de télécharger une copie JSON et de créer
une demande d'accès, rectification, effacement ou opposition. Le traitement des demandes et l'historique des
consentements sont réservés aux rôles autorisés. L'effacement anonymise un dossier et bloque les dossiers ayant une
inscription en cours ; les inscriptions, notes, présences et paiements historiques sont conservés. La durée de
conservation des dossiers inactifs se règle dans les paramètres. `python manage.py anonymiser_dossiers_expires`
affiche les dossiers arrivés à échéance sans les modifier ; ajouter `--appliquer` pour anonymiser, ou
`--etablissement-id ID` pour limiter l'opération.

## Installation

```bash
python -m venv venv 
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # puis adapter les valeurs
```

Base MySQL :

```sql
CREATE DATABASE edugest CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'edugest'@'localhost' IDENTIFIED BY 'mot_de_passe';
GRANT ALL ON edugest.* TO 'edugest'@'localhost';
```

```bash
python manage.py migrate
python manage.py createsuperuser                        # administrateur de la plateforme (console /plateforme/)
python manage.py runserver                              # puis ouvrir http://127.0.0.1:8000 et « Créer mon établissement »
```

Sans configuration SMTP, les e-mails (invitations, confirmation, mot de passe oublié) sont affichés dans le terminal du serveur en développement, mais ne sont pas livrés. L'interface le signale explicitement. Pour envoyer des e-mails, renseigner les variables SMTP ci-dessous dans `.env`.
Pour créer un établissement en ligne de commande : `python manage.py creer_etablissement --nom ... --type SCOLAIRE
--administrateur ... --email ... --mot-de-passe ...`.

Données de démonstration (école, année active, comptes `demo_directeur`, `demo_secretaire`, `demo_enseignant`,
`demo_pedagogue`, `demo_comptable`) : `python manage.py charger_demo` (mot de passe par défaut : `Demo2026!`).

## Variables d'environnement (`.env`)

| Variable | Rôle |
|----------|------|
| `ENVIRONNEMENT` | `developpement`, `production` ou `test` : choisit le fichier de paramètres |
| `CLE_SECRETE` | clé secrète Django (50 caractères minimum, obligatoire en production) |
| `MODE_DEBUG` | `True` / `False` |
| `HOTES_AUTORISES` | domaines autorisés, séparés par des virgules |
| `FUSEAU_HORAIRE` | fuseau horaire (défaut `America/Port-au-Prince`) |
| `COURRIEL_HOTE`, `COURRIEL_PORT`, `COURRIEL_UTILISATEUR`, `COURRIEL_MOT_DE_PASSE`, `COURRIEL_TLS`, `COURRIEL_EXPEDITEUR` | envoi des e-mails (SMTP) ; laisser `COURRIEL_HOTE` vide pour afficher les e-mails dans la console |
| `BD_NOM`, `BD_UTILISATEUR`, `BD_MOT_DE_PASSE`, `BD_HOTE`, `BD_PORT` | connexion MySQL |

`DOSSIER_FICHIERS_PRIVES` et `TAILLE_MAX_FICHIER_MO` configurent le stockage non public des pièces de cahier/devoirs et leur taille maximale (10 Mo par défaut).

`configuration/__init__.py` déclare PyMySQL comme pilote MySQL (`pymysql.install_as_MySQLdb()`).
En production, le projet refuse de démarrer sans clé secrète sûre ni hôtes explicites.

## Tests

```bash
ENVIRONNEMENT=test python manage.py test applications    # SQLite en mémoire, rapide
python manage.py test applications                       # sur MySQL (utilisateur avec droit CREATE)
```

Les tests couvrent les règles métier, les permissions, l'isolation entre établissements, les invitations,
les finances et les parcours complets par l'interface. Ils sont exécutés avec succès sur MariaDB via PyMySQL.

## Organisation

```
configuration/            paramètres (base, developpement, production, test), urls, wsgi/asgi
applications/
  noyau/          comptes, établissements (tenants), rôles, invitations, abonnements, audit, isolation (middleware), pages publiques
  academique/     années, périodes configurables, facultés, programmes, niveaux, classes et campus
  apprenants/     dossiers permanents, responsables, inscriptions, décisions, réinscription et discipline
  pedagogie/      matières, barèmes par niveau et année, dérogations de classe, affectations des enseignants
  evaluations/    composantes libres, notes, historique des corrections, bulletins PDF versionnés/révocables et exports
  finances/       tarifs par niveau et année, factures et échéances, imputations, remboursements et rapports
  presences/      appels, historique et portail d'absences avec notifications aux familles
  cahier/         cahier de textes, publication de devoirs et remises numériques protégées
  messagerie/     conversations privées, diffusion par classe et notifications
  emploi_du_temps/ créneaux, salles et portails d'emploi du temps
  importations/   import CSV/Excel avec aperçu, validation et invitations du personnel
  rgpd/           export de données, demandes, consentements et anonymisation avec conservation historique
  badges/         badges PDF avec QR opaques pour apprenants et enseignants
  interface/      navigation par rôle (barre mobile à 5 accès, sidebar)
templates/
  base.html       gabarit général partagé
  comptes/        profil utilisateur et inscription/connexion (registration)
  noyau/          établissements, abonnements, personnel et plateforme
  interface/      composants partagés et gabarit public
  academique/     gabarits du domaine académique, campus et presets
  apprenants/     gabarits des apprenants et inscriptions scolaires
  pedagogie/      gabarits pédagogiques, ressources et quiz
  presences/     appels et portails de présence
  cahier/        séances, devoirs et travaux des apprenants
  messagerie/    boîte de réception, conversations et notifications
  emploi_du_temps/ gestion et consultations par rôle
  evaluations/    gabarits des évaluations et résultats
static/           fichiers CSS, JavaScript, images et fontes
```

Chaque application : `models.py`, `services.py` (logique métier), `views.py`, `formulaires.py`, `urls.py`, `tests.py`.
**Nommage** : français pour le code (classes, fonctions, variables, dossiers, fichiers), anglais uniquement
pour ce que Django impose (`models`, `urls`, `migrations`, `templates`, `Meta`, `objects`, `settings`...).

## Règles métier clés

- **Isolation** : chaque entité porte `etablissement` ; un gestionnaire filtre côté serveur selon l'établissement
  de la requête, et l'écriture dans un autre établissement est refusée.
- **Années et périodes** : une seule année active par établissement, périodes en nombre libre, ouverture et
  fermeture de la saisie ; aucune inscription sans année active.
- **Inscriptions** : dossier permanent séparé ; statut initial `EN_ATTENTE` ; décision tracée (auteur, date, motif) ;
  pas de doublon par année ; réinscription, redoublement, changement de classe, reprise sans recréer l'apprenant.
- **Barèmes** : par matière, niveau et année ; les classes d'un niveau héritent sans configuration, sauf dérogation.
- **Évaluations** : composantes libres par matière et période ; la somme doit égaler exactement le barème ;
  absent, dispensé et non renseigné ne sont jamais des zéros ; modifications tracées.
- **Notation** : aucune échelle codée en dur ; seuil de réussite (50 % par défaut) et échelle des moyennes
  configurables par établissement.
- **MySQL** : les unicités conditionnelles n'existent pas ; elles sont garanties par les services
  (transactions atomiques et verrous) et couvertes par les tests.

## Modules complémentaires

- Les badges PDF comportent un QR code opaque ; les ressources pédagogiques et les documents de résultats sont privés.
- Les quiz sont auto-corrigés. Les ressources et quiz sont rattachés aux affectations et aux classes existantes.
- Les campus, presets académiques, incidents disciplinaires et remboursements sont gérés dans leurs modules respectifs.

## Limites connues
- Bootstrap 5 et Bootstrap Icons sont embarqués dans `static/` : l'interface fonctionne sans Internet.
- Pas de paiement en ligne ni de sous-domaine par établissement (l'isolation repose sur la session de l'utilisateur).
- Les comptes Parent et Apprenant sont liés à leur dossier au moment de l'invitation; le portail limite les résultats aux dossiers associés.
- Les notifications couvrent les inscriptions en attente, les absences, les devoirs et leurs remises.
