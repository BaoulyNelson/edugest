from django import forms

from applications.apprenants.models import Apprenant

from .models import Consentement, DemandeRGPD


class FormulaireConsentement(forms.Form):
    finalite = forms.ChoiceField(label="Finalité", choices=Consentement.Finalite.choices)
    accorde = forms.ChoiceField(label="Consentement", choices=(("oui", "Accordé"), ("non", "Refusé")))
    note = forms.CharField(label="Précision", required=False, max_length=300)

    def consentement(self):
        return self.cleaned_data["accorde"] == "oui"


class FormulaireDemande(forms.Form):
    apprenant = forms.ModelChoiceField(label="Dossier concerné", queryset=Apprenant.objects.none())
    type = forms.ChoiceField(label="Demande", choices=DemandeRGPD.Type.choices)
    details = forms.CharField(label="Détails", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, apprenants=None, **kwargs):
        super().__init__(*args, **kwargs)
        if apprenants is not None:
            self.fields["apprenant"].queryset = apprenants
        self.fields["apprenant"].widget.attrs["class"] = "form-select"


class FormulaireTraitement(forms.Form):
    action = forms.ChoiceField(
        label="Décision", choices=(("traiter", "Traiter"), ("refuser", "Refuser"))
    )
    reponse = forms.CharField(label="Réponse ou motif", required=False, widget=forms.Textarea(attrs={"rows": 3}))
