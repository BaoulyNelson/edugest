"""Décorateurs de contrôle d'accès (vérification côté serveur)."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .services import verifier_permission


def a_la_permission(request, code):
    return verifier_permission(request.user, getattr(request, "appartenance", None), code)


def permission_requise(*codes):
    """Exige au moins une des permissions indiquées et un établissement courant."""

    def decorateur(vue):
        @wraps(vue)
        @login_required
        def enveloppe(request, *args, **kwargs):
            if request.etablissement is None:
                raise PermissionDenied("Aucun établissement sélectionné.")
            if not any(a_la_permission(request, code) for code in codes):
                raise PermissionDenied("Vous n'avez pas l'autorisation d'effectuer cette action.")
            return vue(request, *args, **kwargs)

        return enveloppe

    return decorateur
