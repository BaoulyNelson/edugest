from django import forms

from .models import Evenement, Publication


class FormulairePublication(forms.ModelForm):
    publiee_le = forms.DateTimeField(
        label="Date de publication",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Publication
        fields = ("type", "titre", "contenu", "statut", "publiee_le")
        widgets = {"contenu": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type"].label = "Type de publication"
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )


class FormulaireEvenement(forms.ModelForm):
    debut = forms.DateTimeField(
        label="Date de début",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    fin = forms.DateTimeField(
        label="Date de fin",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Evenement
        fields = ("titre", "description", "debut", "fin", "lieu", "statut")
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )

    def clean(self):
        donnees = super().clean()
        debut, fin = donnees.get("debut"), donnees.get("fin")
        if debut and fin and fin <= debut:
            self.add_error("fin", "La fin doit être postérieure au début.")
        return donnees
