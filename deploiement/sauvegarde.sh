#!/bin/sh
# Sauvegarde de la base MySQL et des fichiers déposés, avec rotation. À exécuter chaque nuit.
# Variables : BD_HOTE BD_PORT BD_NOM BD_UTILISATEUR BD_MOT_DE_PASSE DOSSIER_MEDIA DOSSIER_SAUVEGARDES JOURS_CONSERVATION
set -eu
DEST="${DOSSIER_SAUVEGARDES:-/sauvegardes}"
HORODATAGE=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"
mysqldump --single-transaction --quick --routines --default-character-set=utf8mb4 \
  -h "${BD_HOTE:-127.0.0.1}" -P "${BD_PORT:-3306}" -u "${BD_UTILISATEUR}" -p"${BD_MOT_DE_PASSE}" "${BD_NOM}" | gzip -9 > "$DEST/base-$HORODATAGE.sql.gz"
[ -d "${DOSSIER_MEDIA:-/app/media}" ] && tar -czf "$DEST/fichiers-$HORODATAGE.tar.gz" -C "${DOSSIER_MEDIA:-/app/media}" .
# Copie hors site (décommenter et configurer) : aws s3 cp "$DEST/base-$HORODATAGE.sql.gz" "s3://MON-BUCKET/edugest/"
find "$DEST" -type f -mtime +"${JOURS_CONSERVATION:-30}" -delete
echo "Sauvegarde terminée : $DEST/base-$HORODATAGE.sql.gz"
