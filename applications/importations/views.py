from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.noyau import saas

from . import services
from .forms import FormulaireImportation
from .models import LotImportation


def _permission_lot(lot):
    return (
        "importations.apprenants"
        if lot.type == LotImportation.Type.APPRENANTS
        else "importations.personnel"
    )


@permission_requise("importations.apprenants", "importations.personnel")
def accueil(request):
    types_autorises = [
        choix for choix in LotImportation.Type.choices
        if a_la_permission(
            request,
            "importations.apprenants"
            if choix[0] == LotImportation.Type.APPRENANTS
            else "importations.personnel",
        )
    ]
    formulaire = FormulaireImportation(
        request.POST or None, request.FILES or None, types_autorises=types_autorises
    )
    if request.method == "POST" and formulaire.is_valid():
        type_import = formulaire.cleaned_data["type_import"]
        permission = (
            "importations.apprenants"
            if type_import == LotImportation.Type.APPRENANTS
            else "importations.personnel"
        )
        if not a_la_permission(request, permission):
            raise PermissionDenied
        try:
            lot = services.analyser_fichier(
                request.etablissement, request.user, type_import, formulaire.cleaned_data["fichier"]
            )
        except ErreurMetier as erreur:
            formulaire.add_error("fichier", str(erreur))
        else:
            messages.info(request, "Vérifiez l'aperçu et les erreurs avant de confirmer l'importation.")
            return redirect("importations:detail", pk=lot.pk)
    return render(request, "importations/accueil.html", {
        "formulaire": formulaire,
        "lots": LotImportation.objects.filter(cree_par=request.user).exclude(lignes=[]),
    })


@permission_requise("importations.apprenants", "importations.personnel")
def detail(request, pk):
    lot = get_object_or_404(LotImportation, pk=pk, cree_par=request.user)
    if not a_la_permission(request, _permission_lot(lot)):
        raise PermissionDenied
    return render(request, "importations/detail.html", {
        "lot": lot, "expire": lot.expire_le <= timezone.now(),
    })


@permission_requise("importations.apprenants", "importations.personnel")
@require_POST
def confirmer(request, pk):
    lot = get_object_or_404(LotImportation, pk=pk, cree_par=request.user)
    if not a_la_permission(request, _permission_lot(lot)):
        raise PermissionDenied
    try:
        resultat = services.confirmer_importation(
            lot, request.user, request.build_absolute_uri("/").rstrip("/")
        )
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
        return redirect("importations:detail", pk=lot.pk)
    if lot.type == LotImportation.Type.PERSONNEL and saas.courriel_en_mode_console():
        messages.warning(
            request,
            f"{len(resultat)} invitation(s) créée(s), mais aucun e-mail n'a été livré : "
            "le message est affiché dans le terminal du serveur. Configurez SMTP pour l'envoyer.",
        )
    else:
        messages.success(request, f"{len(resultat)} ligne(s) importée(s).")
    if lot.type == LotImportation.Type.APPRENANTS:
        return redirect("apprenants:liste")
    return redirect("personnel")


@permission_requise("importations.apprenants", "importations.personnel")
@require_POST
def annuler(request, pk):
    lot = get_object_or_404(LotImportation, pk=pk, cree_par=request.user)
    if not a_la_permission(request, _permission_lot(lot)):
        raise PermissionDenied
    services.annuler_importation(lot, request.user)
    messages.success(request, "L'aperçu a été supprimé.")
    return redirect("importations:accueil")
