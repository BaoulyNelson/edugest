from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier

from . import services
from .forms import FormulaireEvenement, FormulairePublication
from .models import Evenement, Publication


@permission_requise("actualites.consulter", "actualites.gerer")
def liste(request):
    peut_gerer = a_la_permission(request, "actualites.gerer")
    publications = Publication.objects.all()
    evenements = Evenement.objects.all()
    if not peut_gerer:
        maintenant = timezone.now()
        publications = publications.filter(
            statut=Publication.Statut.PUBLIEE, publiee_le__lte=maintenant,
        )
        evenements = evenements.filter(
            statut=Evenement.Statut.PLANIFIE, fin__gte=maintenant,
        )
    return render(request, "actualites/liste.html", {
        "publications": publications,
        "evenements": evenements,
        "peut_gerer": peut_gerer,
    })


@permission_requise("actualites.gerer")
def publication_creer(request):
    formulaire = FormulairePublication(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.creer_publication(
                request.etablissement, request.user, **formulaire.cleaned_data
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Publication enregistrée.")
            return redirect("actualites:liste")
    return render(request, "actualites/publication_form.html", {"formulaire": formulaire})


@permission_requise("actualites.gerer")
def publication_modifier(request, pk):
    publication = get_object_or_404(Publication.objects, pk=pk)
    formulaire = FormulairePublication(request.POST or None, instance=publication)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.modifier_publication(
                publication, request.user, **formulaire.cleaned_data
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Publication mise à jour.")
            return redirect("actualites:liste")
    return render(request, "actualites/publication_form.html", {
        "formulaire": formulaire, "publication": publication,
    })


@permission_requise("actualites.gerer")
@require_POST
def publication_archiver(request, pk):
    publication = get_object_or_404(Publication.objects, pk=pk)
    try:
        services.archiver_publication(publication, request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Publication archivée.")
    return redirect("actualites:liste")


@permission_requise("actualites.gerer")
def evenement_creer(request):
    formulaire = FormulaireEvenement(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.creer_evenement(
                request.etablissement, request.user, **formulaire.cleaned_data
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Événement enregistré.")
            return redirect("actualites:liste")
    return render(request, "actualites/evenement_form.html", {"formulaire": formulaire})


@permission_requise("actualites.gerer")
def evenement_modifier(request, pk):
    evenement = get_object_or_404(Evenement.objects, pk=pk)
    formulaire = FormulaireEvenement(request.POST or None, instance=evenement)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.modifier_evenement(
                evenement, request.user, **formulaire.cleaned_data
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Événement mis à jour.")
            return redirect("actualites:liste")
    return render(request, "actualites/evenement_form.html", {
        "formulaire": formulaire, "evenement": evenement,
    })
