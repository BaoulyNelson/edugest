from datetime import time as datetime_time
from decimal import Decimal

from django import forms
from django.conf import settings

from applications.academique.models import Classe
from applications.pedagogie.models import MatiereNiveau

from .models import Devoir, EntreeCahier, EXTENSIONS_AUTORISEES


class SaisieFichiersMultiple(forms.FileInput):
    allow_multiple_selected = True


class ChampFichiersMultiple(forms.FileField):
    widget = SaisieFichiersMultiple

    def clean(self, data, initial=None):
        if not data:
            return super().clean(data, initial)
        fichiers = data if isinstance(data, (list, tuple)) else [data]
        return [super(ChampFichiersMultiple, self).clean(fichier, initial) for fichier in fichiers]


def _valider_fichier(fichier):
    if fichier.size > getattr(settings, "TAILLE_MAX_FICHIER_MO", 10) * 1024 * 1024:
        raise forms.ValidationError("Le fichier dépasse la taille maximale autorisée.")
    extension = fichier.name.rsplit(".", 1)[-1].lower() if "." in fichier.name else ""
    if extension not in EXTENSIONS_AUTORISEES:
        raise forms.ValidationError("Ce type de fichier n'est pas autorisé.")
    return fichier


class FormulaireBaseCahier(forms.ModelForm):
    def __init__(self, *args, paires, **kwargs):
        super().__init__(*args, **kwargs)
        self.paires = set(paires)
        classes = {classe_id for classe_id, _ in self.paires}
        matieres = {matiere_id for _, matiere_id in self.paires}
        self.fields["classe"].queryset = Classe.objects.filter(pk__in=classes).select_related("niveau")
        self.fields["matiere_niveau"].queryset = MatiereNiveau.objects.filter(
            pk__in=matieres,
        ).select_related("matiere", "niveau")
        self.fields["classe"].widget.attrs["class"] = "form-select"
        self.fields["matiere_niveau"].widget.attrs["class"] = "form-select"

    def clean(self):
        donnees = super().clean()
        classe = donnees.get("classe")
        matiere = donnees.get("matiere_niveau")
        if classe and matiere and (classe.pk, matiere.pk) not in self.paires:
            raise forms.ValidationError("Cette matière n'est pas affectée à la classe choisie.")
        return donnees

    def clean_fichier(self):
        fichier = self.cleaned_data.get("fichier")
        if isinstance(fichier, (list, tuple)):
            return [_valider_fichier(element) for element in fichier]
        return _valider_fichier(fichier) if fichier else fichier


class FormulaireEntree(FormulaireBaseCahier):
    class Meta:
        model = EntreeCahier
        fields = ("classe", "matiere_niveau", "date", "titre", "contenu", "fichier")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "contenu": forms.Textarea(attrs={"rows": 5}),
        }


class FormulaireDevoir(FormulaireBaseCahier):
    fichiers = ChampFichiersMultiple(
        label="Fichiers de consigne",
        required=False,
        help_text="PDF, documents, tableurs ou images. Sélectionnez un ou plusieurs fichiers.",
    )

    class Meta:
        model = Devoir
        fields = (
            "classe", "matiere_niveau", "titre", "consigne", "date_limite", "heure_limite",
            "remise_numerique", "accepter_remises_tardives", "modifier_apres_echeance",
            "bareme",
        )
        widgets = {
            "consigne": forms.Textarea(attrs={"rows": 5}),
            "date_limite": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "heure_limite": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "bareme": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
        }

    def clean_fichiers(self):
        return [
            _valider_fichier(fichier)
            for fichier in (self.cleaned_data.get("fichiers") or [])
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["heure_limite"].required = False
        self.fields["bareme"].required = False
        self.fields["bareme"].min_value = Decimal("0")

    def clean_heure_limite(self):
        heure = self.cleaned_data.get("heure_limite")
        return heure if heure is not None else datetime_time(23, 59)

    def clean_bareme(self):
        bareme = self.cleaned_data.get("bareme")
        return bareme if bareme is not None else Decimal("100")


class FormulaireRemise(forms.Form):
    fichier = ChampFichiersMultiple(
        label="Fichiers de mon travail",
        help_text="Sélectionnez un ou plusieurs fichiers.",
    )
    commentaire = forms.CharField(
        label="Commentaire (facultatif)", required=False, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_fichier(self):
        return [_valider_fichier(fichier) for fichier in self.cleaned_data["fichier"]]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        taille_max = getattr(settings, "TAILLE_MAX_FICHIER_MO", 10)
        self.fields["fichier"].help_text = (
            f"PDF, documents, tableurs ou images. Taille maximale par fichier : {taille_max} Mo."
        )
        self.fields["fichier"].widget.attrs["class"] = "form-control"
        self.fields["fichier"].widget.attrs["multiple"] = True
        self.fields["commentaire"].widget.attrs["class"] = "form-control"


class FormulaireAppreciation(forms.Form):
    appreciation = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
    )
    note = forms.DecimalField(
        required=False, min_value=0, max_digits=7, decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "class": "form-control"}),
    )

    def __init__(self, *args, devoir, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note"].max_value = devoir.bareme
        self.fields["note"].widget.attrs["max"] = str(devoir.bareme)


class FormulaireCorrection(FormulaireAppreciation):
    note = forms.DecimalField(
        label="Note",
        min_value=0,
        max_digits=7,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "class": "form-control"}),
    )

    def __init__(self, *args, devoir, **kwargs):
        super().__init__(*args, devoir=devoir, **kwargs)
        self.fields["note"].max_value = devoir.bareme
        self.fields["note"].widget.attrs["max"] = str(devoir.bareme)
        self.fields["note"].help_text = f"Sur {devoir.bareme}."
