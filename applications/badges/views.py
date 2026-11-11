from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from applications.academique.models import Classe
from applications.apprenants.models import Inscription
from applications.noyau.decorateurs import permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance

from . import services
from .models import BadgeGenere


@permission_requise("apprenants.consulter", "apprenants.gerer", "utilisateurs.gerer")
def liste(request):
    return render(request, "badges/liste.html", {
        "classes": Classe.objects.filter(annee__statut="ACTIVE").select_related("niveau", "site"),
    })


@permission_requise("apprenants.consulter", "apprenants.gerer")
def classe_pdf(request, pk):
    classe = get_object_or_404(Classe.objects.select_related("annee"), pk=pk)
    inscriptions = Inscription.objects.filter(
        classe=classe, annee=classe.annee, statut=Inscription.Statut.VALIDEE
    ).select_related("apprenant", "classe").order_by("apprenant__nom", "apprenant__prenoms")
    cibles = [(BadgeGenere.Type.APPRENANT, inscription) for inscription in inscriptions]
    return _reponse_pdf(request, cibles, f"badges-{classe.pk}.pdf")


@permission_requise("utilisateurs.gerer")
def enseignants_pdf(request):
    enseignants = Appartenance.objects.filter(
        actif=True, role__nom="Enseignant"
    ).select_related("utilisateur", "role")
    cibles = [(BadgeGenere.Type.ENSEIGNANT, appartenance) for appartenance in enseignants]
    return _reponse_pdf(request, cibles, "badges-enseignants.pdf")


def _reponse_pdf(request, cibles, nom_fichier):
    try:
        contenu = services.generer_badges(request.etablissement, cibles, request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
        return render(request, "badges/liste.html", {
            "classes": Classe.objects.filter(annee__statut="ACTIVE").select_related("niveau", "site"),
        }, status=400)
    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    return reponse
