"""Paramètres communs à tous les environnements."""
from pathlib import Path

from decouple import Csv, config

RACINE_PROJET = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("CLE_SECRETE", default="")
DEBUG = config("MODE_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("HOTES_AUTORISES", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "applications.comptes",
    "applications.noyau",
    "applications.academique",
    "applications.apprenants",
    "applications.pedagogie",
    "applications.evaluations",
    "applications.finances",
    "applications.presences",
    "applications.cahier",
    "applications.messagerie",
    "applications.emploi_du_temps",
    "applications.importations",
    "applications.rgpd",
    "applications.admissions",
    "applications.interface",
    "applications.badges",
    "applications.actualites",
]

AUTH_USER_MODEL = "noyau.Utilisateur"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "applications.noyau.middleware.MiddlewareEtablissement",
    "applications.noyau.middleware.MiddlewareLocalisation",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "configuration.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [RACINE_PROJET / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "applications.interface.contexte.contexte_interface",
            ],
        },
    },
]

WSGI_APPLICATION = "configuration.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": config("BD_NOM", default="edugest"),
        "USER": config("BD_UTILISATEUR", default="root"),
        "PASSWORD": config("BD_MOT_DE_PASSE", default=""),
        "HOST": config("BD_HOTE", default="localhost"),
        "PORT": config("BD_PORT", default="3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
LANGUAGES = [
    ("fr", "Français"),
    ("en", "English"),
    ("es", "Español"),
    ("ht", "Kreyòl ayisyen"),
]
LOCALE_PATHS = [RACINE_PROJET / "locale"]
TIME_ZONE = config("FUSEAU_HORAIRE", default="America/Port-au-Prince")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [RACINE_PROJET / "static"]
STATIC_ROOT = RACINE_PROJET / "fichiers_statiques"
MEDIA_URL = "media/"
MEDIA_ROOT = RACINE_PROJET / "media"
PRIVATE_MEDIA_ROOT = Path(config("DOSSIER_FICHIERS_PRIVES", default=RACINE_PROJET / "fichiers_prives"))
TAILLE_MAX_FICHIER_MO = config("TAILLE_MAX_FICHIER_MO", default=10, cast=int)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = ["applications.comptes.authentification.BackendEmail"]

# Courriels (invitations, confirmation d'adresse, réinitialisation du mot de passe).
# Par défaut : affichage dans la console. En production, renseigner COURRIEL_HOTE.
_COURRIEL_HOTE = config("COURRIEL_HOTE", default="")
if _COURRIEL_HOTE:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _COURRIEL_HOTE
    EMAIL_PORT = config("COURRIEL_PORT", default=587, cast=int)
    EMAIL_HOST_USER = config("COURRIEL_UTILISATEUR", default="")
    EMAIL_HOST_PASSWORD = config("COURRIEL_MOT_DE_PASSE", default="")
    EMAIL_USE_TLS = config("COURRIEL_TLS", default=True, cast=bool)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = config("COURRIEL_EXPEDITEUR", default="EduGest <no-reply@edugest.local>")

LOGIN_URL = "connexion"
LOGIN_REDIRECT_URL = "tableau_de_bord"
LOGOUT_REDIRECT_URL = "accueil_public"
