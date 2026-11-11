# Image unique pour l'application (web, tâches planifiées, migrations).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gettext curl default-mysql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Fichiers statiques versionnés et compressés (servis par WhiteNoise, mis en cache par le CDN) + catalogues de traduction compilés.
RUN CLE_SECRETE=construction BD_MOTEUR=sqlite DEBUG=False FORCER_HTTPS=False python manage.py collectstatic --noinput \
 && for l in en es; do msgfmt -o locale/$l/LC_MESSAGES/django.mo locale/$l/LC_MESSAGES/django.po; done
RUN useradd --create-home --uid 10001 edugest && mkdir -p /app/media && chown -R edugest /app/media /app/fichiers_statiques
USER edugest
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 CMD curl -fsS http://127.0.0.1:8000/sante/ || exit 1
ENTRYPOINT ["/app/deploiement/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-c", "deploiement/gunicorn.conf.py"]
