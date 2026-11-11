from django import forms

from applications.academique.models import Classe


class FormulaireAppel(forms.Form):
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    date = forms.DateField(
        label="Date de l'appel",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, classes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classe"].queryset = classes
        self.fields["classe"].widget.attrs["class"] = "form-select"
        self.fields["date"].widget.attrs["class"] = "form-control"
