"""Paramètres de production : refuse de démarrer sans configuration sûre."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS as _HOTES
from .base import SECRET_KEY as _CLE

if len(_CLE) < 50:
    raise ImproperlyConfigured("CLE_SECRETE doit contenir au moins 50 caractères en production.")
if not _HOTES or "*" in _HOTES:
    raise ImproperlyConfigured("HOTES_AUTORISES doit lister explicitement les domaines autorisés.")

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
