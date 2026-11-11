"""Configuration gunicorn : adaptée à un conteneur derrière un proxy (nginx, ingress ou CDN)."""
import multiprocessing
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_PROCESSUS", max(2, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.environ.get("GUNICORN_FILS", 2))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_DELAI", 45))
graceful_timeout = 30  # laisse les requêtes en cours se terminer lors d'un déploiement progressif
keepalive = 5
max_requests = 2000  # recyclage régulier des processus (fuites mémoire éventuelles)
max_requests_jitter = 200
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"
worker_tmp_dir = "/dev/shm"
