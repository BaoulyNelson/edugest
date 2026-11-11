"""Paramètres de développement."""
from .base import *  # noqa: F401,F403
from .base import SECRET_KEY as _CLE

DEBUG = True
SECRET_KEY = _CLE or "cle-de-developpement-non-securisee"
