from django import forms
from django.utils import timezone

from applications.academique.models import AnneeAcademique, Classe
from applications.noyau.models import Etablissement, TypeEtablissement

from .models import Candidature


class FormulaireCandidature(forms.ModelForm):
    etablissement = forms.ModelChoiceField(
        label="Établissement souhaité",
        queryset=Etablissement.objects.filter(actif=True, type=TypeEtablissement.SCOLAIRE),
    )

    class Meta:
        model = Candidature
        fields = (
            "etablissement", "nom", "prenoms", "sexe", "date_naissance", "lieu_naissance",
            "classe", "nom_parent", "telephone_parent", "email_parent", "message",
        )
        widgets = {
            "date_naissance": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "message": forms.Textarea(attrs={"rows": 4}),
        }

    consentement = forms.BooleanField(
        label="J’accepte que l’établissement traite ces informations pour étudier cette candidature."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classe"].queryset = Classe.objects.none()
        self.fields["sexe"].required = False
        self.fields["lieu_naissance"].required = False
        self.fields["message"].required = False
        etablissement_id = self.data.get("etablissement") or self.initial.get("etablissement")
        if etablissement_id:
            etablissement = Etablissement.objects.filter(
                pk=etablissement_id, actif=True, type=TypeEtablissement.SCOLAIRE
            ).first()
            if etablissement is not None:
                annee = AnneeAcademique.sans_filtre.filter(
                    etablissement=etablissement, statut=AnneeAcademique.Statut.ACTIVE
                ).first()
                if annee is not None:
                    self.fields["classe"].queryset = Classe.sans_filtre.filter(
                        etablissement=etablissement, annee=annee
                    ).select_related("niveau")
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        donnees = super().clean()
        etablissement = donnees.get("etablissement")
        classe = donnees.get("classe")
        date_naissance = donnees.get("date_naissance")
        if date_naissance and date_naissance > timezone.localdate():
            self.add_error("date_naissance", "La date de naissance ne peut pas être dans le futur.")
        if etablissement and classe and classe.etablissement_id != etablissement.pk:
            self.add_error("classe", "La classe choisie ne correspond pas à cet établissement.")
        if etablissement and classe:
            annee = AnneeAcademique.sans_filtre.filter(
                etablissement=etablissement, statut=AnneeAcademique.Statut.ACTIVE
            ).first()
            if annee is None or classe.annee_id != annee.pk:
                self.add_error("classe", "Cette classe n’est pas disponible pour l’année active.")
        return donnees

    def save(self, commit=True):
        candidature = super().save(commit=False)
        candidature.etablissement = self.cleaned_data["etablissement"]
        candidature.annee = candidature.classe.annee
        candidature.consentement_donnees = self.cleaned_data["consentement"]
        candidature.consentement_le = timezone.now()
        if commit:
            candidature.save()
        return candidature


class FormulaireDecisionCandidature(forms.Form):
    motif = forms.CharField(
        label="Motif (facultatif)", required=False, max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
