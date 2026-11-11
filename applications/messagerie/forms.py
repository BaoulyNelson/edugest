from django import forms

from applications.academique.models import Classe
from applications.noyau.models import Utilisateur

from . import services


class FormulaireMessage(forms.Form):
    destinataires = forms.ModelMultipleChoiceField(
        label="Destinataires",
        queryset=Utilisateur.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 6, "class": "form-select"}),
    )
    classe = forms.ModelChoiceField(
        label="Ou : diffuser aux élèves et responsables d'une classe",
        queryset=Classe.objects.none(),
        required=False,
    )
    sujet = forms.CharField(label="Sujet", max_length=150)
    texte = forms.CharField(label="Message", widget=forms.Textarea(attrs={"rows": 5}))

    def __init__(
        self, *args, utilisateur, etablissement, appartenance,
        peut_diffuser, classes, **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["destinataires"].queryset = services.destinataires_autorises(
            utilisateur, etablissement, appartenance,
        )
        self.fields["destinataires"].label_from_instance = lambda membre: membre.nom_affiche
        if peut_diffuser:
            self.fields["classe"].queryset = classes
            self.fields["classe"].widget.attrs["class"] = "form-select"
        else:
            del self.fields["classe"]
        self.fields["sujet"].widget.attrs["class"] = "form-control"
        self.fields["texte"].widget.attrs["class"] = "form-control"

    def clean(self):
        donnees = super().clean()
        if not donnees.get("destinataires") and not donnees.get("classe"):
            raise forms.ValidationError("Choisissez au moins un destinataire ou une classe.")
        return donnees


class FormulaireReponse(forms.Form):
    texte = forms.CharField(
        label="Votre réponse",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )
