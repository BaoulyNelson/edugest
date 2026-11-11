from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from applications.academique.models import Classe
from applications.academique.services import annee_active
from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier

from . import services
from .forms import FormulaireCreneau, FormulaireSalle
from .models import Creneau, Salle


@permission_requise("emploi.voir")
def gestion(request):
    annee = annee_active(request.etablissement)
    classes = (
        Classe.objects.filter(etablissement=request.etablissement, annee=annee).select_related("niveau")
        if annee else Classe.objects.none()
    )
    classe = classes.filter(pk=request.GET.get("classe")).first() if request.GET.get("classe") else classes.first()
    return render(request, "emploi_du_temps/gestion.html", {
        "classes": classes,
        "classe": classe,
        "jours": services.regrouper_par_jour(services.creneaux_de_classe(classe)) if classe else [],
        "peut_gerer": a_la_permission(request, "emploi.gerer"),
        "annee": annee,
    })


@permission_requise("emploi.gerer")
def creneau_creer(request):
    formulaire = FormulaireCreneau(
        request.POST or None,
        etablissement=request.etablissement,
        initial={"affectation": request.GET.get("affectation")},
    )
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            creneau = services.creer_creneau(
                etablissement=request.etablissement,
                affectation=donnees["affectation"],
                jour=int(donnees["jour"]),
                heure_debut=donnees["heure_debut"],
                heure_fin=donnees["heure_fin"],
                salle=donnees["salle"],
                acteur=request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Créneau ajouté.")
            return redirect(f"{reverse('emploi_du_temps:gestion')}?classe={creneau.affectation.classe_id}")
    return render(request, "emploi_du_temps/creneau_form.html", {"formulaire": formulaire})


@permission_requise("emploi.gerer")
@require_POST
def creneau_supprimer(request, pk):
    creneau = get_object_or_404(Creneau.objects.select_related("affectation__classe"), pk=pk)
    classe_id = creneau.affectation.classe_id
    try:
        services.supprimer_creneau(creneau, request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Créneau supprimé.")
    return redirect(f"{reverse('emploi_du_temps:gestion')}?classe={classe_id}")


@permission_requise("emploi.enseigner", "emploi.consulter")
def mon_emploi(request):
    if a_la_permission(request, "emploi.enseigner"):
        creneaux = services.creneaux_de_l_enseignant(request.appartenance, request.etablissement)
        titre = "Mon emploi du temps"
    elif a_la_permission(request, "emploi.consulter"):
        creneaux = services.creneaux_de_la_famille(request.user, request.etablissement)
        titre = "Emploi du temps"
    else:
        raise PermissionDenied
    return render(request, "emploi_du_temps/mon_emploi.html", {
        "jours": services.regrouper_par_jour(creneaux),
        "titre": titre,
    })


@permission_requise("emploi.voir")
def salles(request):
    return render(request, "emploi_du_temps/salles.html", {
        "salles": Salle.objects.all(),
    })


@permission_requise("emploi.gerer")
def salle_creer(request):
    formulaire = FormulaireSalle(request.POST or None, etablissement=request.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        salle = formulaire.save(commit=False)
        salle.etablissement = request.etablissement
        salle.save()
        messages.success(request, "Salle ajoutée.")
        return redirect("emploi_du_temps:salles")
    return render(request, "emploi_du_temps/salle_form.html", {"formulaire": formulaire})
