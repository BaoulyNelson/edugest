from django import forms

from applications.academique.services import annee_active
from applications.noyau.models import Appartenance
from applications.pedagogie.models import AffectationEnseignant

from .models import JOURS, Salle


class FormulaireSalle(forms.ModelForm):
    class Meta:
        model = Salle
        fields = ("nom", "capacite")
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "capacite": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }

    def __init__(self, *args, etablissement, **kwargs):
        self.etablissement = etablissement
        super().__init__(*args, **kwargs)

    def clean_nom(self):
        nom = self.cleaned_data["nom"].strip()
        salles = Salle.objects.filter(etablissement=self.etablissement, nom__iexact=nom)
        if self.instance.pk:
            salles = salles.exclude(pk=self.instance.pk)
        if salles.exists():
            raise forms.ValidationError("Une salle porte déjà ce nom.")
        return nom


class FormulaireCreneau(forms.Form):
    affectation = forms.ModelChoiceField(
        label="Enseignant, matière et classe",
        queryset=AffectationEnseignant.objects.none(),
    )
    jour = forms.ChoiceField(label="Jour", choices=JOURS)
    heure_debut = forms.TimeField(
        label="Début", widget=forms.TimeInput(attrs={"type": "time"}),
    )
    heure_fin = forms.TimeField(
        label="Fin", widget=forms.TimeInput(attrs={"type": "time"}),
    )
    salle = forms.ModelChoiceField(
        label="Salle", queryset=Salle.objects.none(), required=False,
    )

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        annee = annee_active(etablissement)
        affectations = AffectationEnseignant.objects.none()
        if annee:
            affectations = AffectationEnseignant.objects.filter(
                etablissement=etablissement,
                matiere_niveau__annee=annee,
                classe__isnull=False,
            ).select_related(
                "appartenance__utilisateur", "matiere_niveau__matiere", "classe",
            )
        self.fields["affectation"].queryset = affectations
        self.fields["affectation"].label_from_instance = lambda affectation: (
            f"{affectation.classe} · {affectation.matiere_niveau.matiere} · "
            f"{affectation.appartenance.utilisateur.nom_affiche}"
        )
        self.fields["salle"].queryset = Salle.objects.filter(etablissement=etablissement)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
