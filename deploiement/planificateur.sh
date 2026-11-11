#!/bin/sh
# Planificateur léger (sans cron) : à lancer dans UN conteneur dédié par plateforme.
#  - chaque minute : relevé des métriques du nœud ;
#  - chaque jour (03:10) : facturation des abonnements, relances, suspensions ;
#  - chaque mois (le 1er, 04:00) : application de la durée de conservation RGPD ;
#  - chaque nuit (02:00) : sauvegarde.
set -u
derniere_minute=""
while true; do
  maintenant=$(date +%H:%M)
  jour=$(date +%d)
  if [ "$maintenant" != "$derniere_minute" ]; then
    derniere_minute="$maintenant"
    python manage.py collecter_metriques >/dev/null 2>&1 || echo "collecter_metriques a échoué"
    [ "$maintenant" = "03:10" ] && python manage.py traiter_abonnements
    [ "$maintenant" = "04:00" ] && [ "$jour" = "01" ] && python manage.py appliquer_retention_rgpd --appliquer
    [ "$maintenant" = "02:00" ] && [ -x deploiement/sauvegarde.sh ] && deploiement/sauvegarde.sh
  fi
  sleep 20
done
