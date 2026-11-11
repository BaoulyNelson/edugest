from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from applications.apprenants.models import Apprenant
from applications.noyau.decorateurs import permission_requise
from applications.noyau.exceptions import ErreurMetier

from . import services
from .forms import FormulaireConsentement, FormulaireDemande, FormulaireTraitement
from .models import Consentement, DemandeRGPD


@permission_requise("rgpd.demander")
def mes_donnees(request):
    apprenants = services.apprenants_accessibles(request.user, request.etablissement)
    formulaire = FormulaireDemande(request.POST or None, apprenants=apprenants)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.creer_demande(
                formulaire.cleaned_data["apprenant"], request.user,
                formulaire.cleaned_data["type"], formulaire.cleaned_data["details"],
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Votre demande a été enregistrée. Elle sera traitée dans les 30 jours.")
            return redirect("rgpd:mes_donnees")
    return render(request, "rgpd/mes_donnees.html", {
        "apprenants": apprenants, "formulaire": formulaire,
        "demandes": DemandeRGPD.objects.filter(demandeur=request.user).select_related("apprenant"),
    })


@permission_requise("rgpd.demander")
def exporter(request, pk):
    apprenant = get_object_or_404(
        services.apprenants_accessibles(request.user, request.etablissement), pk=pk
    )
    donnees = services.exporter_donnees(apprenant, request.user)
    reponse = JsonResponse(donnees, json_dumps_params={"ensure_ascii": False, "indent": 2})
    reponse["Content-Disposition"] = f'attachment; filename="donnees-apprenant-{apprenant.pk}.json"'
    return reponse


@permission_requise("rgpd.gerer")
def demandes(request):
    return render(request, "rgpd/demandes.html", {
        "demandes": DemandeRGPD.objects.select_related("apprenant", "demandeur"),
        "formulaire": FormulaireTraitement(),
    })


@permission_requise("rgpd.gerer")
@require_POST
def traiter(request, pk):
    demande = get_object_or_404(DemandeRGPD.objects.select_related("apprenant"), pk=pk)
    formulaire = FormulaireTraitement(request.POST)
    if not formulaire.is_valid():
        messages.error(request, "La décision envoyée est invalide.")
        return redirect("rgpd:demandes")
    try:
        services.traiter_demande(
            demande, formulaire.cleaned_data["action"], formulaire.cleaned_data["reponse"], request.user
        )
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "La demande a été mise à jour.")
    return redirect("rgpd:demandes")


@permission_requise("rgpd.gerer")
def consentements(request, pk):
    apprenant = get_object_or_404(Apprenant, pk=pk)
    formulaire = FormulaireConsentement(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.enregistrer_consentement(
                apprenant, formulaire.cleaned_data["finalite"], formulaire.consentement(),
                formulaire.cleaned_data["note"], request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Le consentement a été enregistré dans l'historique.")
            return redirect("rgpd:consentements", pk=apprenant.pk)
    return render(request, "rgpd/consentements.html", {
        "apprenant": apprenant, "formulaire": formulaire,
        "consentements": Consentement.objects.filter(apprenant=apprenant),
    })


@permission_requise("rgpd.gerer")
@require_POST
def anonymiser(request, pk):
    apprenant = get_object_or_404(Apprenant, pk=pk)
    try:
        services.anonymiser_apprenant(apprenant, request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Les données personnelles du dossier ont été anonymisées.")
    return redirect("apprenants:detail", pk=apprenant.pk)
