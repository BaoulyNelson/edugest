"""Point d'entrée ASGI."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "configuration.parametres")
application = get_asgi_application()
