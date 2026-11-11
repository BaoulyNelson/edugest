"""Chargement des paramètres selon la variable d'environnement ENVIRONNEMENT.

Valeurs possibles : developpement (par défaut), production, test.
"""
from importlib import import_module

from decouple import config

ENVIRONNEMENT = config("ENVIRONNEMENT", default="developpement")

if ENVIRONNEMENT not in ("developpement", "production", "test"):
    raise RuntimeError(
        f"ENVIRONNEMENT invalide : « {ENVIRONNEMENT} ». "
        "Valeurs autorisées : developpement, production, test."
    )

_module = import_module(f"{__name__}.{ENVIRONNEMENT}")
globals().update({nom: valeur for nom, valeur in vars(_module).items() if nom.isupper()})
