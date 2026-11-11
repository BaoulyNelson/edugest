from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from applications.academique.models import Classe
from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier
from . import services
from .forms import FormulaireAppel
from .models import AppelPresence, LignePresence, NotificationPresence


@permission_requise("presences.saisir")
def appel(request):
    classes = services.classes_accessibles(
        request.etablissement, request.appartenance, request.user,
    )
    jour_initial = timezone.localdate().isoformat()
    premiere_classe = classes.first()
    donnees = request.POST if request.method == "POST" else request.GET
    if request.method == "GET" and not donnees and premiere_classe is not None:
        donnees = {"classe": str(premiere_classe.pk), "date": jour_initial}
    formulaire = FormulaireAppel(
        donnees or None,
        classes=classes,
        initial={"date": jour_initial},
    )
    lignes = []
    appel_existant = None
    if formulaire.is_valid():
        classe = formulaire.cleaned_data["classe"]
        jour = formulaire.cleaned_data["date"]
        try:
            services.valider_date_appel(classe, jour)
        except ErreurMetier as erreur:
            formulaire.add_error("date", str(erreur))
        else:
            appel_existant = AppelPresence.objects.filter(classe=classe, date=jour).first()
            existantes = {
                ligne.inscription_id: ligne
                for ligne in appel_existant.lignes.all()
            } if appel_existant else {}
            inscrits = services.inscrits(classe)
            if request.method == "POST" and request.POST.get("enregistrer"):
                if not inscrits:
                    messages.error(request, "Aucun apprenant validé n'est inscrit dans cette classe.")
                    return redirect(f"{request.path}?classe={classe.pk}&date={jour.isoformat()}")
                saisies = {
                    inscription.pk: (
                        request.POST.get(f"statut_{inscription.pk}", LignePresence.Statut.PRESENT),
                        request.POST.get(f"motif_{inscription.pk}", ""),
                    )
                    for inscription in inscrits
                }
                try:
                    appel_existant = appel_existant or services.obtenir_appel(
                        classe, jour, request.user,
                    )
                    absents = services.enregistrer_appel(
                        appel_existant, saisies, request.appartenance, request.user,
                    )
                except ErreurMetier as erreur:
                    messages.error(request, str(erreur))
                else:
                    messages.success(request, f"Appel enregistré. {absents} absence(s) notée(s).")
                    return redirect(f"{request.path}?classe={classe.pk}&date={jour.isoformat()}")
            lignes = [
                {
                    "inscription": inscription,
                    "statut": (
                        existantes[inscription.pk].statut
                        if inscription.pk in existantes else LignePresence.Statut.PRESENT
                    ),
                    "motif": existantes[inscription.pk].motif if inscription.pk in existantes else "",
                }
                for inscription in inscrits
            ]
    return render(request, "presences/appel.html", {
        "formulaire": formulaire,
        "lignes": lignes,
        "statuts": LignePresence.Statut.choices,
        "appel_existant": appel_existant,
        "peut_consulter": a_la_permission(request, "presences.consulter"),
    })


@permission_requise("presences.consulter")
def liste(request):
    classes = Classe.objects.select_related("niveau", "annee").order_by("-annee__date_debut", "niveau__ordre", "nom")
    classe_id = request.GET.get("classe")
    classe = classes.filter(pk=classe_id).first() if classe_id else None
    return render(request, "presences/liste.html", {
        "classes": classes,
        "classe": classe,
        "appels": services.historique(classe),
    })


@permission_requise("presences.consulter_propres")
def mes_absences(request):
    NotificationPresence.objects.filter(
        etablissement=request.etablissement, destinataire=request.user, lue=False,
    ).update(lue=True)
    bilans = [
        (apprenant, services.bilan_apprenant(apprenant))
        for apprenant in services.apprenants_associes(request.user, request.etablissement)
    ]
    return render(request, "presences/mes_absences.html", {"bilans": bilans})
