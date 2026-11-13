from django import forms

from applications.academique.models import Classe
from applications.emploi_du_temps.models import Salle
from applications.pedagogie.models import MatiereNiveau

from .models import Examen


class FormulaireExamen(forms.ModelForm):
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
        model = Examen
        fields = ("matiere_niveau", "classe", "intitule", "debut", "fin", "salle", "consignes")
        widgets = {"consignes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, etablissement, annee, **kwargs):
        super().__init__(*args, **kwargs)
        matieres = MatiereNiveau.objects.none()
        classes = Classe.objects.none()
        if annee is not None:
            matieres = MatiereNiveau.objects.filter(
                etablissement=etablissement, annee=annee
            ).select_related("matiere", "niveau")
            classes = Classe.objects.filter(etablissement=etablissement, annee=annee).select_related("niveau")
        self.fields["matiere_niveau"].queryset = matieres
        self.fields["matiere_niveau"].label_from_instance = lambda item: (
            f"{item.matiere} · {item.niveau}"
        )
        self.fields["classe"].queryset = classes
        self.fields["classe"].required = False
        self.fields["classe"].empty_label = "Tout le niveau"
        self.fields["salle"].queryset = Salle.objects.filter(etablissement=etablissement)
        self.fields["salle"].required = False
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
