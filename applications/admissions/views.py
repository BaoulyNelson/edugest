from django.contrib import messages
from django.core.paginator import Paginator
from django import forms
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from applications.noyau import saas
from applications.noyau.decorateurs import permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Etablissement, TypeEtablissement

from . import services
from .forms import FormulaireCandidature, FormulaireDecisionCandidature
from .models import Candidature


def deposer(request):
    etablissements = Etablissement.objects.filter(actif=True, type=TypeEtablissement.SCOLAIRE)
    etablissement_id = request.POST.get("etablissement") or request.GET.get("etablissement")
    etablissement = etablissements.filter(pk=etablissement_id).first() if etablissement_id else None
    formulaire = FormulaireCandidature(
        request.POST or None, initial={"etablissement": etablissement.pk} if etablissement else None
    )
    if etablissement:
        formulaire.fields["etablissement"].widget = forms.HiddenInput()
    if request.method == "POST" and formulaire.is_valid():
        candidature = services.deposer_candidature(formulaire)
        return render(request, "admissions/confirmation.html", {"candidature": candidature})
    return render(request, "admissions/deposer.html", {
        "formulaire": formulaire, "etablissements": etablissements, "etablissement_choisi": etablissement is not None,
    })


@permission_requise("inscriptions.decider")
def liste(request):
    statut = request.GET.get("statut", "")
    candidatures = Candidature.objects.select_related("classe", "annee")
    if statut in Candidature.Statut.values:
        candidatures = candidatures.filter(statut=statut)
    page = Paginator(candidatures, 20).get_page(request.GET.get("page"))
    return render(request, "admissions/liste.html", {
        "page": page, "statut": statut, "statuts": Candidature.Statut.choices,
    })


@permission_requise("inscriptions.decider")
def detail(request, reference):
    candidature = get_object_or_404(
        Candidature.objects.select_related("classe__niveau", "annee", "apprenant_cree", "inscription_creee"),
        reference=reference,
    )
    return render(request, "admissions/detail.html", {
        "candidature": candidature, "formulaire_decision": FormulaireDecisionCandidature(),
    })


@permission_requise("inscriptions.decider")
@require_POST
def action(request, reference):
    candidature = get_object_or_404(Candidature.objects, reference=reference)
    action_demandee = request.POST.get("action")
    try:
        if action_demandee == "accepter":
            candidature, invitation = services.accepter_candidature(
                candidature, request.user, request.build_absolute_uri("/").rstrip("/")
            )
            if invitation is None:
                messages.success(request, "Candidature acceptée et inscription validée; le compte Parent existant a été associé.")
            elif saas.courriel_en_mode_console():
                messages.warning(request, "La candidature est acceptée. L’invitation du parent est affichée dans le terminal du serveur, sans lui être livrée.")
            else:
                messages.success(request, "Candidature acceptée, inscription validée et invitation du parent envoyée.")
        elif action_demandee == "refuser":
            formulaire = FormulaireDecisionCandidature(request.POST)
            if not formulaire.is_valid():
                messages.error(request, "Le motif de décision est invalide.")
                return redirect("admissions:detail", reference=reference)
            services.refuser_candidature(candidature, request.user, formulaire.cleaned_data["motif"])
            messages.success(request, "Candidature refusée.")
        else:
            messages.error(request, "Action inconnue.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("admissions:detail", reference=reference)
