from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from applications.noyau.decorateurs import permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import vocabulaire

from . import services
from .forms import (
    FormulaireAnnee, FormulaireClasse, FormulaireDatesAnnee, FormulaireFaculte, FormulaireNiveau, FormulaireNom, FormulairePeriode,
    FormulairePresetAcademique, FormulaireProgramme, FormulaireSite,
)
from .models import (
    AnneeAcademique, Classe, Faculte, Niveau, Periode, PresetAcademique,
    Programme, SiteEtablissement,
)


@permission_requise("academique.gerer")
def annees(request):
    return render(request, "academique/annees.html", {"annees": AnneeAcademique.objects.all()})


@permission_requise("academique.gerer")
def annee_creer(request):
    formulaire = FormulaireAnnee(request.POST or None, etablissement=request.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        try:
            annee = services.creer_annee(request.etablissement, par=request.user, **formulaire.cleaned_data)
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, f"L'année {annee} a été créée avec ses périodes.")
            return redirect("academique:periodes", pk=annee.pk)
    return render(request, "academique/annee_form.html", {"formulaire": formulaire})


@permission_requise("academique.gerer")
@require_POST
def annee_action(request, pk):
    annee = get_object_or_404(AnneeAcademique, pk=pk)
    action = request.POST.get("action")
    try:
        if action == "activer":
            services.activer_annee(annee, par=request.user)
            messages.success(request, f"L'année {annee} est maintenant active.")
        elif action == "cloturer":
            services.cloturer_annee(annee, par=request.user)
            messages.success(request, f"L'année {annee} est clôturée.")
        elif action == "modifier_dates":
            formulaire = FormulaireDatesAnnee(request.POST)
            if not formulaire.is_valid():
                erreurs = "; ".join(
                    erreur for erreurs_champ in formulaire.errors.values() for erreur in erreurs_champ
                )
                raise ErreurMetier(f"Vérifiez les dates de l'année : {erreurs}")
            services.modifier_dates_annee(annee, par=request.user, **formulaire.cleaned_data)
            messages.success(request, f"Les dates de l'année {annee} ont été mises à jour.")
        elif action == "dupliquer":
            source = get_object_or_404(AnneeAcademique, pk=request.POST.get("source"))
            classes, matieres = services.dupliquer_annee(source, annee, par=request.user)
            messages.success(request, f"{classes} classe(s) et {matieres} matière(s) reprises de {source}.")
        else:
            messages.error(request, "Action inconnue.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("academique:periodes", pk=annee.pk)


@permission_requise("academique.gerer")
def periodes(request, pk):
    annee = get_object_or_404(AnneeAcademique, pk=pk)
    sources = AnneeAcademique.objects.exclude(pk=annee.pk)
    return render(request, "academique/periodes.html", {
        "annee": annee, "periodes": annee.periodes.all(), "sources": sources,
        "formulaire_dates_annee": FormulaireDatesAnnee(annee=annee),
        "formulaire_periode": FormulairePeriode(annee=annee),
        "libelle_periode": vocabulaire(request.etablissement, "periode", pluriel=True),
    })


@permission_requise("academique.gerer")
@require_POST
def periode_creer(request, pk):
    annee = get_object_or_404(AnneeAcademique, pk=pk)
    formulaire = FormulairePeriode(request.POST, annee=annee)
    if formulaire.is_valid():
        try:
            periode = services.creer_periode(annee, par=request.user, **formulaire.cleaned_data)
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, f"{periode.nom} a été ajoutée à l'année {annee}.")
            return redirect("academique:periodes", pk=annee.pk)
    return render(request, "academique/periodes.html", {
        "annee": annee, "periodes": annee.periodes.all(),
        "sources": AnneeAcademique.objects.exclude(pk=annee.pk),
        "formulaire_periode": formulaire,
        "libelle_periode": vocabulaire(request.etablissement, "periode", pluriel=True),
    })


@permission_requise("academique.gerer")
@require_POST
def periode_action(request, pk):
    periode = get_object_or_404(Periode, pk=pk)
    action = request.POST.get("action")
    try:
        if action == "ouvrir":
            services.ouvrir_periode(periode, par=request.user)
            messages.success(request, f"{periode.nom} est ouverte, la saisie des notes est autorisée.")
        elif action == "fermer":
            services.fermer_periode(periode, par=request.user)
            messages.success(request, f"{periode.nom} est clôturée.")
        elif action == "saisie_on":
            services.basculer_saisie(periode, True, par=request.user)
            messages.success(request, "Saisie des notes rouverte.")
        elif action == "saisie_off":
            services.basculer_saisie(periode, False, par=request.user)
            messages.success(request, "Saisie des notes suspendue.")
        elif action == "modifier":
            formulaire = FormulairePeriode(request.POST)
            if not formulaire.is_valid():
                erreurs = "; ".join(
                    erreur for erreurs_champ in formulaire.errors.values() for erreur in erreurs_champ
                )
                raise ErreurMetier(f"Vérifiez les informations de la période : {erreurs}")
            services.modifier_periode(periode, par=request.user, **formulaire.cleaned_data)
            messages.success(request, f"{periode.nom} a été mise à jour.")
        else:
            messages.error(request, "Action inconnue.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("academique:periodes", pk=periode.annee_id)


@permission_requise("academique.gerer")
def structure(request):
    """Niveaux, classes (école) ou facultés, programmes et niveaux (université) sur une seule page."""
    etablissement = request.etablissement
    annee = services.annee_active(etablissement)
    formulaires = {
        "niveau": FormulaireNiveau(prefix="niveau", etablissement=etablissement),
        "classe": FormulaireClasse(prefix="classe"),
        "faculte": FormulaireFaculte(prefix="faculte"),
        "programme": FormulaireProgramme(prefix="programme"),
        "site": FormulaireSite(prefix="site"),
        "preset": FormulairePresetAcademique(prefix="preset"),
    }
    if request.method == "POST":
        cible = request.POST.get("cible")
        classes_formulaires = {
            "niveau": lambda d: FormulaireNiveau(d, prefix="niveau", etablissement=etablissement),
            "classe": lambda d: FormulaireClasse(d, prefix="classe"),
            "faculte": lambda d: FormulaireFaculte(d, prefix="faculte"),
            "programme": lambda d: FormulaireProgramme(d, prefix="programme"),
            "site": lambda d: FormulaireSite(d, prefix="site"),
            "preset": lambda d: FormulairePresetAcademique(d, prefix="preset"),
        }
        if cible in classes_formulaires:
            formulaire = classes_formulaires[cible](request.POST)
            formulaires[cible] = formulaire
            if formulaire.is_valid():
                donnees = formulaire.cleaned_data
                try:
                    if cible == "niveau":
                        services.creer_niveau(etablissement, donnees["nom"], donnees.get("programme"))
                    elif cible == "classe":
                        if annee is None:
                            raise ErreurMetier("Activez d'abord une année académique pour créer des classes.")
                        services.creer_classe(
                            donnees["niveau"], annee, donnees["nom"], donnees.get("effectif_max"),
                            donnees.get("site"),
                        )
                    elif cible == "faculte":
                        services.creer_faculte(etablissement, donnees["nom"])
                    elif cible == "programme":
                        services.creer_programme(donnees["faculte"], donnees["nom"])
                    elif cible == "site":
                        site = formulaire.save(commit=False)
                        site.etablissement = etablissement
                        site.save()
                    elif cible == "preset":
                        if PresetAcademique.sans_filtre.filter(
                            etablissement=etablissement, nom__iexact=donnees["nom"].strip()
                        ).exists():
                            raise ErreurMetier("Un preset porte déjà ce nom.")
                        PresetAcademique.sans_filtre.create(
                            etablissement=etablissement, nom=donnees["nom"].strip(),
                            niveaux=donnees["niveaux"],
                        )
                except ErreurMetier as erreur:
                    messages.error(request, str(erreur))
                else:
                    messages.success(request, "Enregistré.")
                    return redirect("academique:structure")
    return render(request, "academique/structure.html", {
        "annee": annee, "formulaires": formulaires,
        "niveaux": Niveau.objects.select_related("programme"),
        "classes": Classe.objects.filter(annee=annee).select_related("niveau") if annee else [],
        "facultes": Faculte.objects.prefetch_related("programmes"),
        "sites": SiteEtablissement.objects.filter(actif=True),
        "presets": PresetAcademique.objects.filter(actif=True),
        "libelle_niveau": vocabulaire(etablissement, "niveau", pluriel=True),
    })


@permission_requise("academique.gerer")
@require_POST
def appliquer_preset(request, pk):
    preset = get_object_or_404(PresetAcademique, pk=pk, actif=True)
    try:
        creees = services.appliquer_preset(preset, par=request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, f"{len(creees)} niveau(x) ajouté(s) depuis « {preset.nom} ».")
    return redirect("academique:structure")


@permission_requise("academique.gerer")
def niveau_modifier(request, pk):
    niveau = get_object_or_404(Niveau, pk=pk)
    formulaire = FormulaireNom(request.POST or None, initial={"nom": niveau.nom})
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.modifier_niveau(niveau, formulaire.cleaned_data["nom"], par=request.user)
        except ErreurMetier as erreur:
            formulaire.add_error("nom", str(erreur))
        else:
            messages.success(request, "Le nom du niveau a été corrigé.")
            return redirect("academique:structure")
    return render(request, "academique/nom_form.html", {
        "formulaire": formulaire, "objet": niveau, "titre": "Modifier le niveau", "est_niveau": True,
    })


@permission_requise("academique.gerer")
@require_POST
def niveau_supprimer(request, pk):
    niveau = get_object_or_404(Niveau, pk=pk)
    try:
        services.supprimer_niveau(niveau, par=request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, f"Le niveau « {niveau} » a été supprimé.")
    return redirect("academique:structure")


@permission_requise("academique.gerer")
def classe_modifier(request, pk):
    classe = get_object_or_404(Classe, pk=pk)
    formulaire = FormulaireNom(request.POST or None, initial={"nom": classe.nom})
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.modifier_classe(classe, formulaire.cleaned_data["nom"], par=request.user)
        except ErreurMetier as erreur:
            formulaire.add_error("nom", str(erreur))
        else:
            messages.success(request, "Le nom de la classe a été corrigé.")
            return redirect("academique:structure")
    return render(request, "academique/nom_form.html", {
        "formulaire": formulaire, "objet": classe, "titre": "Modifier la classe",
    })
