"""Établissement courant de la requête (isolation des données entre tenants).

La valeur est un identifiant d'établissement. ``None`` signifie « aucun filtre »
(shell, commandes, administrateur de la plateforme sans sélection). La valeur
``0`` ne correspond à aucun établissement : toute requête filtrée renvoie alors
un résultat vide.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_etablissement_courant = ContextVar("etablissement_courant", default=None)


def definir_etablissement_courant(identifiant):
    return _etablissement_courant.set(identifiant)


def reinitialiser_etablissement_courant(jeton):
    _etablissement_courant.reset(jeton)


def obtenir_etablissement_courant():
    return _etablissement_courant.get()


@contextmanager
def etablissement_courant(etablissement):
    """Active l'isolation pour un établissement donné (utile dans les tests et les commandes)."""
    jeton = definir_etablissement_courant(etablissement.pk if etablissement else None)
    try:
        yield
    finally:
        reinitialiser_etablissement_courant(jeton)


def sans_isolation(fonction):
    """Décorateur pour les opérations qui créent ou rattachent des données d'un AUTRE établissement
    (création d'un espace, acceptation d'une invitation) : le filtrage de la requête est suspendu."""
    from functools import wraps

    @wraps(fonction)
    def enveloppe(*args, **kwargs):
        jeton = definir_etablissement_courant(None)
        try:
            return fonction(*args, **kwargs)
        finally:
            reinitialiser_etablissement_courant(jeton)

    return enveloppe
