# Mise en production d'EduGest : CDN, haute disponibilité, exploitation

## 1. Architecture cible

```
Utilisateurs ──► DNS wildcard (*.votre-domaine) ──► CDN / WAF (TLS, cache, DDoS)
                                                      │ origine
                                       Répartiteur de charge / Ingress (certificat wildcard)
                                                      │
                  ┌───────────────────────────────────┴──────────────────────────────┐
                  │  Pods « web » (3 à 20, gunicorn, sans état, multi-zones)          │
                  └──────┬──────────────────────┬─────────────────────┬──────────────┘
                         │                      │                     │
              MySQL haute dispo         Redis (cache + sessions)   Stockage de fichiers partagé
          (multi-zone, bascule auto)                                (RWX ou stockage objet)
                  CronJobs : métriques (1 min) · abonnements (nuit) · RGPD (mois) · sauvegardes (nuit)
```

Les nœuds applicatifs ne conservent aucun état local : sessions et cache sont dans Redis, fichiers sur stockage partagé, données dans MySQL. On peut donc ajouter, retirer ou redémarrer des nœuds à tout moment.

## 2. Démarrage rapide (un hôte, Docker)

```bash
cp .env.exemple .env      # renseigner CLE_SECRETE, BD_*, DOMAINE_PLATEFORME, HOTES_AUTORISES, ORIGINES_CSRF_FIABLES
docker compose -f docker-compose.production.yml --env-file .env up -d --build --scale web=3
docker compose -f docker-compose.production.yml exec web python manage.py createsuperuser   # compte de l'éditeur (console /plateforme/)
```

La migration de la base et la création des formules d'abonnement s'exécutent automatiquement (service `migration`). Le conteneur `planificateur` lance les tâches récurrentes.

## 3. Kubernetes (haute disponibilité multi-hôtes)

`kubectl apply -f deploiement/kubernetes/edugest.yaml` après avoir remplacé les valeurs « CHANGER » : image, secrets, hôte MySQL, domaine.
Ce qui est fourni : 3 réplicas minimum répartis par zone, mise à jour progressive sans indisponibilité (`maxUnavailable: 0`), sondes de vivacité (`/sante/`) et de disponibilité (`/sante/prete/` : base, cache, migrations),
autoscaling (CPU 65 %, jusqu'à 20 pods), budget d'interruption (2 pods toujours disponibles), Ingress wildcard TLS, tâches planifiées (`CronJob`).

**Déploiement sans interruption** : (1) construire l'image ; (2) lancer le Job de migration (les migrations doivent rester rétro-compatibles avec la version N-1 : ajouter avant de supprimer) ; (3) mettre à jour l'image du Deployment : les pods sont remplacés un par un, seuls les pods « prêts » reçoivent du trafic.

## 4. CDN

- **Fichiers statiques** : noms versionnés (WhiteNoise `CompressedManifestStaticFilesStorage`), `Cache-Control: public, max-age=31536000, immutable`. Définir `URL_CDN=https://cdn.votre-domaine/statique/` et faire pointer le CDN vers l'origine (`/statique/`). Bootstrap et les icônes viennent déjà d'un CDN public.
- **Pages publiques du site vitrine** (`/`, `/tarifs/`, `/fonctionnalites/`, `/conditions/`, `/confidentialite/`, `/mentions-legales/`) : l'application émet `Cache-Control: public, s-maxage=3600`. Règle CDN : mettre en cache ces chemins en ignorant les cookies, avec la langue (`?lang=`) dans la clé de cache.
- **Pages connectées** : l'application émet `private, no-store` (jamais de contenu d'établissement dans un cache partagé). Règle CDN : **ne rien mettre en cache** pour tous les autres chemins, transmettre `Host`, `Cookie`, `X-Forwarded-Proto`.
- **Sécurité en périphérie** : WAF, limitation de débit (en plus du nginx fourni), certificat wildcard `*.votre-domaine`, HSTS déjà émis par l'application.
- **Performances mondiales** : activer le « origin shield », HTTP/3, compression Brotli. L'en-tête `Server-Timing` permet de mesurer le temps passé dans l'application.

## 5. Données, régions et conformité

- Chaque établissement indique sa **région d'hébergement** (Paramètres). Pour une résidence des données stricte (Europe, Amérique du Nord…), déployer une pile complète par région et router chaque sous-domaine vers sa région au niveau DNS/CDN.
- **Base de données** : MySQL géré en multi-zone avec bascule automatique (RDS Multi-AZ, Cloud SQL HA ou Group Replication), RPO < 1 min, RTO < 5 min. Charset `utf8mb4`. Un réplica en lecture peut être ajouté pour les rapports.
- **Sauvegardes** : `deploiement/sauvegarde.sh` (base + fichiers, rotation 30 jours, copie hors site à configurer). **Exercer la restauration chaque trimestre** : `gunzip -c base-*.sql.gz | mysql ...` puis `python manage.py migrate`.
- **RGPD** : tâche mensuelle `appliquer_retention_rgpd --appliquer` (anonymisation après la durée de conservation de chaque établissement) ; export, effacement et consentements dans l'application ; les journaux d'audit sont conservés 5 ans.

## 6. Supervision

- Sondes : `/sante/` (vivacité) et `/sante/prete/` (disponibilité) pour l'orchestrateur, le CDN et les outils de supervision externes (UptimeRobot, Pingdom, Prometheus blackbox…).
- Console de l'éditeur (`/plateforme/supervision/`, super-administrateur) : relevés par nœud (processeur, mémoire, disque, latence de la base, requêtes, requêtes lentes, erreurs 5xx, sessions), alertes automatiques à seuils (attention/critique) et historique. Alimentée par `python manage.py collecter_metriques` chaque minute sur chaque nœud.
- Journaux au format texte sur la sortie standard : à collecter (Loki, ELK, CloudWatch). Seuil de requête lente : `SEUIL_REQUETE_LENTE_SECONDES`.

## 7. Paiements en ligne : passer de la simulation à la production

La passerelle fournie est **simulée** (aucun débit réel). Le cycle est celui d'une passerelle hébergée : création de l'opération, redirection vers la page de paiement, retour signé (HMAC), finalisation **idempotente**. Pour brancher un prestataire (Stripe, PayPal, MonCash…), il suffit de remplacer dans `applications/plateforme/passerelle.py` `url_paiement()` (création de la session chez le prestataire) et `verifier_signature()` (vérification de la signature de son webhook) ; les gestionnaires métier (`finaliser_paiement_en_ligne`, activation d'abonnement) ne changent pas. Prévoir une route de webhook qui appelle `passerelle.finaliser()`.

## 8. Liste de contrôle avant ouverture commerciale

- [ ] `DEBUG=False`, `CLE_SECRETE` unique et secrète, `python manage.py check --deploy` sans erreur
- [ ] DNS et certificat wildcard en place, `DOMAINE_PLATEFORME`, `HOTES_AUTORISES` (`.domaine`) et `ORIGINES_CSRF_FIABLES` (`https://*.domaine`) renseignés
- [ ] MySQL en haute disponibilité, Redis, stockage partagé des fichiers
- [ ] Sauvegarde nocturne testée, restauration exercée
- [ ] Planificateur actif (métriques, abonnements, RGPD) et alertes reliées à une astreinte
- [ ] Prestataire de paiement réel branché et testé (voir §7) ; mentions légales et CGU complétées par le service juridique
- [ ] Courriel transactionnel configuré (`EMAIL_*`), expéditeur et SPF/DKIM
- [ ] Test de charge et test de bascule (arrêt d'un pod, d'un nœud, de la base) réalisés
