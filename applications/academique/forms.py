from datetime import date

from django import forms

from applications.interface.forms import annoter_relations_ajout_rapide

from .models import Faculte, Niveau, Periode, PresetAcademique, Programme, SiteEtablissement
from applications.noyau.models import ParametresEtablissement
from applications.noyau.services import vocabulaire


def _style(formulaire):
    for champ in formulaire.fields.values():
        if isinstance(champ.widget, (forms.Select, forms.SelectMultiple)):
            champ.widget.attrs["class"] = "form-select"
        elif not isinstance(champ.widget, forms.CheckboxInput):
            champ.widget.attrs["class"] = "form-control"
    annoter_relations_ajout_rapide(formulaire)


class FormulaireAnnee(forms.Form):
    designation = forms.CharField(label="Désignation", max_length=20, help_text="Exemple : 2026-2027")
    date_debut = forms.DateField(label="Début", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_fin = forms.DateField(label="Fin", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    nombre_periodes = forms.IntegerField(label="Nombre de périodes", min_value=1, max_value=12,
                                         help_text="Trimestres ou semestres : modifiables ensuite.")

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        annee = date.today().year
        if not self.is_bound:
            self.initial = {
                "designation": f"{annee}-{annee + 1}", "date_debut": date(annee, 9, 1),
                "date_fin": date(annee + 1, 6, 30),
                "nombre_periodes": (
                    ParametresEtablissement.objects.get(etablissement=etablissement).nombre_periodes_par_annee
                    if etablissement is not None
                    else 3
                ),
            }
        _style(self)


class FormulaireDatesAnnee(forms.Form):
    date_debut = forms.DateField(label="Début", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_fin = forms.DateField(label="Fin", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, annee=None, **kwargs):
        super().__init__(*args, **kwargs)
        if annee is not None and not self.is_bound:
            self.initial = {"date_debut": annee.date_debut, "date_fin": annee.date_fin}
        _style(self)

    def clean(self):
        donnees = super().clean()
        debut = donnees.get("date_debut")
        fin = donnees.get("date_fin")
        if debut and fin and fin <= debut:
            self.add_error("date_fin", "La date de fin doit être postérieure à la date de début.")
        return donnees


class FormulairePeriode(forms.Form):
    nom = forms.CharField(label="Nom", max_length=60)
    date_debut = forms.DateField(label="Début", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_fin = forms.DateField(label="Fin", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, annee=None, **kwargs):
        super().__init__(*args, **kwargs)
        if annee is not None and not self.is_bound:
            ordre = (Periode.objects.filter(annee=annee).count() or 0) + 1
            self.initial["nom"] = f"{vocabulaire(annee.etablissement, 'periode')} {ordre}"
        _style(self)


class FormulaireNiveau(forms.Form):
    nom = forms.CharField(label="Nom du niveau", max_length=100)
    programme = forms.ModelChoiceField(label="Programme", queryset=Programme.objects.none(), required=False)

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if etablissement is not None and etablissement.est_universitaire:
            self.fields["programme"].queryset = Programme.objects.all()
            self.fields["programme"].required = True
        else:
            del self.fields["programme"]
        _style(self)


class FormulaireNom(forms.Form):
    nom = forms.CharField(label="Nom", max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireClasse(forms.Form):
    niveau = forms.ModelChoiceField(label="Niveau", queryset=Niveau.objects.none())
    site = forms.ModelChoiceField(label="Site / campus", queryset=SiteEtablissement.objects.none(), required=False)
    nom = forms.CharField(label="Nom de la classe", max_length=50, help_text="Exemple : 7e A")
    effectif_max = forms.IntegerField(label="Effectif maximal", required=False, min_value=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["niveau"].queryset = Niveau.objects.all()
        self.fields["site"].queryset = SiteEtablissement.objects.filter(actif=True)
        _style(self)


class FormulaireFaculte(forms.Form):
    nom = forms.CharField(label="Nom de la faculté", max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireProgramme(forms.Form):
    faculte = forms.ModelChoiceField(label="Faculté", queryset=Faculte.objects.none())
    nom = forms.CharField(label="Nom du programme", max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["faculte"].queryset = Faculte.objects.all()
        _style(self)
        self.fields["faculte"].widget.attrs.pop("data-ajout-rapide", None)


class FormulaireSite(forms.ModelForm):
    class Meta:
        model = SiteEtablissement
        fields = ["nom", "code", "adresse", "telephone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulairePresetAcademique(forms.Form):
    nom = forms.CharField(label="Nom du preset", max_length=100)
    niveaux = forms.CharField(
        label="Niveaux (un par ligne)", widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Exemple : 7e année, 8e année, 9e année.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def clean_niveaux(self):
        niveaux = [ligne.strip() for ligne in self.cleaned_data["niveaux"].splitlines() if ligne.strip()]
        if not niveaux:
            raise forms.ValidationError("Indiquez au moins un niveau.")
        if len({nom.casefold() for nom in niveaux}) != len(niveaux):
            raise forms.ValidationError("Chaque niveau doit être unique.")
        return niveaux
