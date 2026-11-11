#!/usr/bin/env python
"""Point d'entrée des commandes d'administration Django."""
import os
import sys


def principal():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "configuration.parametres")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django est introuvable. Installez les dépendances : pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    principal()
