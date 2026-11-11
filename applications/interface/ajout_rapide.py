"""Création asynchrone d'entités référentielles depuis un champ relationnel."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from applications.academique import services as services_academiques
from applications.academique.models import Classe, Faculte, Niveau, Programme
from applications.academique.services import annee_active
from applications.apprenants import services as services_apprenants
from applications.apprenants.models import Apprenant, ResponsableLegal
from applications.noyau.decorateurs import a_la_permission
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import TypeEtablissement
from applications.pedagogie import services as services_pedagogie
from applications.pedagogie.models import Matiere, MatiereNiveau


PERMISSIONS = {
    "apprenant": "apprenants.gerer",
    "responsable": "utilisateurs.gerer",
    "matiere": "pedagogie.gerer",
    "faculte": "academique.gerer",
    "programme": "academique.gerer",
    "niveau": "academique.gerer",
    "classe": "academique.gerer",
    "matiere_niveau": "pedagogie.gerer",
}


class FormulaireAjoutApprenant(forms.Form):
    nom = forms.CharField(label="Nom", max_length=100)
    prenoms = forms.CharField(label="Prénoms", max_length=150)
    sexe = forms.ChoiceField(label="Sexe", choices=Apprenant.Sexe.choices)
    date_naissance = forms.DateField(
        label="Date de naissance", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )


class FormulaireAjoutResponsable(forms.Form):
    nom = forms.CharField(label="Nom", max_length=100)
    prenoms = forms.CharField(label="Prénoms", max_length=150, required=False)
    telephone = forms.CharField(label="Téléphone", max_length=30, required=False)
    email = forms.EmailField(label="Adresse e-mail", required=False)

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()


class FormulaireAjoutMatiere(forms.Form):
    nom = forms.CharField(label="Nom de la matière", max_length=150)


class FormulaireAjoutFaculte(forms.Form):
    nom = forms.CharField(label="Nom de la faculté", max_length=150)

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement

    def clean_nom(self):
        nom = self.cleaned_data["nom"].strip()
        if Faculte.objects.filter(etablissement=self.etablissement, nom__iexact=nom).exists():
            raise forms.ValidationError("Cette faculté existe déjà.")
        return nom


class FormulaireAjoutProgramme(forms.Form):
    faculte = forms.ModelChoiceField(label="Faculté", queryset=Faculte.objects.none())
    nom = forms.CharField(label="Nom du programme", max_length=150)

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["faculte"].queryset = Faculte.objects.filter(etablissement=etablissement)

    def clean(self):
        donnees = super().clean()
        faculte, nom = donnees.get("faculte"), donnees.get("nom", "").strip()
        if nom:
            donnees["nom"] = nom
        if faculte and nom and Programme.objects.filter(faculte=faculte, nom__iexact=nom).exists():
            self.add_error("nom", "Ce programme existe déjà dans cette faculté.")
        return donnees


class FormulaireAjoutNiveau(forms.Form):
    nom = forms.CharField(label="Nom du niveau", max_length=100)
    programme = forms.ModelChoiceField(label="Programme", queryset=Programme.objects.none(), required=False)

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        if etablissement.est_universitaire:
            self.fields["programme"].queryset = Programme.objects.filter(etablissement=etablissement)
            self.fields["programme"].required = True
        else:
            del self.fields["programme"]

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()


class FormulaireAjoutClasse(forms.Form):
    niveau = forms.ModelChoiceField(label="Niveau", queryset=Niveau.objects.none())
    nom = forms.CharField(label="Nom de la classe", max_length=50)
    effectif_max = forms.IntegerField(label="Effectif maximal", min_value=1, required=False)

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["niveau"].queryset = Niveau.objects.filter(etablissement=etablissement)

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()


class FormulaireAjoutMatiereNiveau(forms.Form):
    niveau = forms.ModelChoiceField(label="Niveau", queryset=Niveau.objects.none())
    matiere = forms.ModelChoiceField(label="Matière", queryset=Matiere.objects.none())
    bareme = forms.DecimalField(label="Barème", min_value=1, max_digits=7, decimal_places=2)
    coefficient = forms.DecimalField(label="Coefficient", min_value=0.01, max_digits=5, decimal_places=2, initial=1)

    def __init__(self, *args, etablissement, annee, initial=None, **kwargs):
        super().__init__(*args, initial=initial, **kwargs)
        self.etablissement = etablissement
        self.annee = annee
        self.fields["niveau"].queryset = Niveau.objects.filter(etablissement=etablissement)
        self.fields["matiere"].queryset = Matiere.objects.filter(etablissement=etablissement)


def _formulaire(cible, request, donnees=None, initial=None):
    etablissement = request.etablissement
    classes = {
        "apprenant": (FormulaireAjoutApprenant, {}),
        "responsable": (FormulaireAjoutResponsable, {}),
        "matiere": (FormulaireAjoutMatiere, {}),
        "faculte": (FormulaireAjoutFaculte, {"etablissement": etablissement}),
        "programme": (FormulaireAjoutProgramme, {"etablissement": etablissement}),
        "niveau": (FormulaireAjoutNiveau, {"etablissement": etablissement}),
        "classe": (FormulaireAjoutClasse, {"etablissement": etablissement}),
    }
    if cible == "matiere_niveau":
        annee = annee_active(etablissement)
        if annee is None:
            raise ValueError("Aucune année académique active.")
        initial = dict(initial or {})
        classe_id = initial.pop("classe", None)
        if classe_id:
            classe = Classe.objects.filter(etablissement=etablissement, annee=annee, pk=classe_id).first()
            if classe:
                initial["niveau"] = classe.niveau_id
        return FormulaireAjoutMatiereNiveau(
            donnees, etablissement=etablissement, annee=annee, initial=initial
        )
    classe, options = classes[cible]
    return classe(donnees, initial=initial, **options) if donnees is not None else classe(initial=initial, **options)


def _schema(formulaire):
    champs = []
    for nom, champ in formulaire.fields.items():
        donnees = {
            "name": nom,
            "label": str(champ.label or nom),
            "required": champ.required,
            "type": champ.widget.input_type if hasattr(champ.widget, "input_type") else "text",
        }
        initial = formulaire.get_initial_for_field(champ, nom)
        if hasattr(initial, "pk"):
            initial = initial.pk
        if initial is not None:
            donnees["value"] = str(initial)
        if isinstance(champ, (forms.ChoiceField, forms.ModelChoiceField)):
            donnees["type"] = "select"
            donnees["choices"] = [
                {"value": str(valeur), "label": str(libelle)}
                for valeur, libelle in champ.choices if str(valeur)
            ]
        if isinstance(champ, forms.DecimalField):
            donnees["step"] = "0.01"
            donnees["min"] = str(champ.min_value) if champ.min_value is not None else "0"
        champs.append(donnees)
    return champs


def _erreurs(formulaire):
    return {
        nom: [str(erreur) for erreur in erreurs]
        for nom, erreurs in formulaire.errors.items()
    }


@login_required
@require_http_methods(["GET", "POST"])
def ajout_rapide(request, cible):
    if cible not in PERMISSIONS:
        return JsonResponse({"error": "Type d'entité non pris en charge."}, status=404)
    if request.etablissement is None:
        raise PermissionDenied("Aucun établissement sélectionné.")
    if not a_la_permission(request, PERMISSIONS[cible]):
        raise PermissionDenied("Vous n'avez pas l'autorisation de créer cette entité.")
    if cible == "responsable" and request.etablissement.type != TypeEtablissement.SCOLAIRE:
        return JsonResponse({"error": "Les responsables légaux sont réservés aux écoles classiques."}, status=400)
    if cible == "faculte" and not request.etablissement.est_universitaire:
        return JsonResponse({"error": "Les facultés ne concernent que les universités."}, status=400)
    if cible == "classe" and request.etablissement.est_universitaire:
        return JsonResponse({"error": "Les universités n'utilisent pas de classes."}, status=400)

    annee = annee_active(request.etablissement) if cible == "classe" else None
    if cible == "classe" and annee is None:
        return JsonResponse({"error": "Activez une année académique avant de créer une classe."}, status=400)
    if cible == "matiere_niveau" and annee_active(request.etablissement) is None:
        return JsonResponse({"error": "Activez une année académique avant de configurer une matière."}, status=400)

    if request.method == "GET":
        initial = {
            cle: request.GET.get(cle)
            for cle in ("faculte", "programme", "niveau", "classe")
            if request.GET.get(cle)
        }
        try:
            formulaire = _formulaire(cible, request, initial=initial)
        except ValueError as erreur:
            return JsonResponse({"error": str(erreur)}, status=400)
        return JsonResponse({"fields": _schema(formulaire)})

    initial = {
        cle: request.GET.get(cle)
        for cle in ("faculte", "programme", "niveau", "classe")
        if request.GET.get(cle)
    }
    try:
        formulaire = _formulaire(cible, request, donnees=request.POST, initial=initial)
    except ValueError as erreur:
        return JsonResponse({"error": str(erreur)}, status=400)
    if not formulaire.is_valid():
        return JsonResponse({"errors": _erreurs(formulaire)}, status=400)

    donnees = formulaire.cleaned_data
    try:
        with transaction.atomic():
            if cible == "apprenant":
                objet = services_apprenants.creer_apprenant(
                    request.etablissement, donnees["nom"], donnees["prenoms"], donnees["sexe"],
                    donnees["date_naissance"],
                )
            elif cible == "responsable":
                objet = services_apprenants.creer_responsable(
                    request.etablissement, donnees["nom"], donnees["prenoms"],
                    donnees["telephone"], donnees["email"],
                )
            elif cible == "matiere":
                objet = services_pedagogie.creer_matiere(request.etablissement, donnees["nom"])
            elif cible == "faculte":
                objet = services_academiques.creer_faculte(request.etablissement, donnees["nom"])
            elif cible == "programme":
                objet = services_academiques.creer_programme(donnees["faculte"], donnees["nom"])
            elif cible == "niveau":
                objet = services_academiques.creer_niveau(
                    request.etablissement, donnees["nom"], donnees.get("programme")
                )
            elif cible == "matiere_niveau":
                objet = services_pedagogie.definir_matiere_niveau(
                    annee_active(request.etablissement), donnees["niveau"], donnees["matiere"],
                    donnees["bareme"], donnees["coefficient"], par=request.user,
                )
            else:
                objet = services_academiques.creer_classe(
                    donnees["niveau"], annee, donnees["nom"], donnees.get("effectif_max")
                )
    except ErreurMetier as erreur:
        return JsonResponse({"errors": {"__all__": [str(erreur)]}}, status=400)
    except IntegrityError:
        return JsonResponse(
            {"errors": {"__all__": ["Une entité portant ces informations existe déjà."]}},
            status=400,
        )

    relations = {}
    if cible == "programme":
        relations["faculte"] = objet.faculte_id
    elif cible == "niveau" and objet.programme_id:
        relations["programme"] = objet.programme_id
    elif cible == "classe":
        relations["niveau"] = objet.niveau_id
    elif cible == "matiere_niveau":
        relations["niveau"] = objet.niveau_id
    resultat = {"id": objet.pk, "label": str(objet), "relations": relations}
    if cible == "responsable":
        resultat["champs_parent"] = {"email": objet.email}
    return JsonResponse(resultat, status=201)
