#!/bin/sh
# Attend la base de données, applique les migrations si demandé, puis lance la commande.
set -e
if [ "${BD_MOTEUR:-mysql}" = "mysql" ]; then
  echo "Attente de la base de données ${BD_HOTE:-127.0.0.1}:${BD_PORT:-3306}…"
  i=0
  until python - <<PY
import os, sys, socket
try:
    socket.create_connection((os.environ.get("BD_HOTE", "127.0.0.1"), int(os.environ.get("BD_PORT", "3306"))), 2).close()
except OSError:
    sys.exit(1)
PY
  do
    i=$((i+1)); [ "$i" -gt 60 ] && echo "Base de données injoignable" && exit 1
    sleep 2
  done
fi
if [ "${EXECUTER_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py initialiser_plans
fi
exec "$@"
