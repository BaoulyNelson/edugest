from django import forms

from .models import LotImportation


class FormulaireImportation(forms.Form):
    type_import = forms.ChoiceField(label="Données à importer", choices=LotImportation.Type.choices)
    fichier = forms.FileField(label="Fichier CSV ou Excel (.csv, .xlsx)")

    def __init__(self, *args, types_autorises=None, **kwargs):
        super().__init__(*args, **kwargs)
        if types_autorises is not None:
            self.fields["type_import"].choices = types_autorises
        self.fields["type_import"].widget.attrs["class"] = "form-select"
        self.fields["fichier"].widget.attrs["class"] = "form-control"

    def clean_fichier(self):
        fichier = self.cleaned_data["fichier"]
        if not fichier.name.casefold().endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Choisissez un fichier .csv ou .xlsx.")
        return fichier
