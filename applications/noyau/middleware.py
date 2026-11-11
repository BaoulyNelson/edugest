"""Détermine l'établissement courant, applique l'abonnement et active l'isolation des données."""
from django.conf import settings
from django.utils import timezone, translation
from django.utils.cache import patch_vary_headers
from django.shortcuts import render

from .contexte import definir_etablissement_courant, reinitialiser_etablissement_courant
from .models import Appartenance
from .saas import etat_abonnement

# Pages restant accessibles même si l'abonnement est suspendu (pour se déconnecter ou changer d'espace).
CHEMINS_LIBRES = ("/deconnexion/", "/etablissements/", "/abonnement/", "/static/", "/media/", "/plateforme/", "/administration/")


def determiner_contexte(request):
    """Renvoie (établissement, appartenance) pour l'utilisateur connecté."""
    utilisateur = request.user
    if utilisateur.is_superuser:
        appartenance = Appartenance.sans_filtre.filter(
            utilisateur=utilisateur,
            etablissement_id=request.session.get("etablissement_id"),
            actif=True,
            etablissement__actif=True,
        ).select_related("etablissement", "role").first()
        if appartenance is not None:
            return appartenance.etablissement, appartenance
        request.session.pop("etablissement_id", None)
        return None, None
    identifiant = request.session.get("etablissement_id")
    appartenances = list(
        Appartenance.sans_filtre.filter(utilisateur=utilisateur, actif=True, etablissement__actif=True)
        .select_related("etablissement", "role")
        .order_by("etablissement__nom")
    )
    choisie = next((a for a in appartenances if a.etablissement_id == identifiant), None)
    if choisie is None and appartenances:
        choisie = appartenances[0]
        request.session["etablissement_id"] = choisie.etablissement_id
    if choisie is not None:
        return choisie.etablissement, choisie
    return None, None


class MiddlewareEtablissement:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.etablissement = None
        request.appartenance = None
        request.abonnement_bloque = False
        jeton = None
        utilisateur = getattr(request, "user", None)
        if utilisateur is not None and utilisateur.is_authenticated:
            if utilisateur.is_superuser:
                if request.path.startswith(("/plateforme/", "/administration/", "/etablissements/")):
                    etablissement, appartenance = None, None
                else:
                    etablissement, appartenance = determiner_contexte(request)
            else:
                etablissement, appartenance = determiner_contexte(request)
            request.etablissement = etablissement
            request.appartenance = appartenance
            if etablissement is not None:
                identifiant = etablissement.pk
                actif, message = etat_abonnement(etablissement)
                if not actif:
                    request.abonnement_bloque = True
                    if not request.path.startswith(CHEMINS_LIBRES):
                        return render(request, "noyau/abonnement_suspendu.html", {"message": message}, status=402)
            elif utilisateur.is_superuser:
                identifiant = None
            else:
                identifiant = 0  # aucun établissement : aucune donnée visible
            jeton = definir_etablissement_courant(identifiant)
        try:
            return self.get_response(request)
        finally:
            if jeton is not None:
                reinitialiser_etablissement_courant(jeton)


class MiddlewareLocalisation:
    """Applique la langue de session ou, par défaut, celle du tenant courant."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.langues = {code for code, _ in settings.LANGUAGES}

    def __call__(self, request):
        langue_session = request.session.get("langue_interface")
        langue_tenant = getattr(request.etablissement, "langue", settings.LANGUAGE_CODE)
        langue = langue_session if langue_session in self.langues else langue_tenant
        fuseau = getattr(request.etablissement, "fuseau_horaire", settings.TIME_ZONE)
        with translation.override(langue), timezone.override(fuseau):
            response = self.get_response(request)
        patch_vary_headers(response, ("Cookie",))
        response.headers["Content-Language"] = langue
        return response
