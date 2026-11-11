from datetime import date
from decimal import Decimal

from django import forms

from applications.academique.models import AnneeAcademique, Niveau
from applications.apprenants.models import Apprenant
from applications.interface.forms import annoter_relations_ajout_rapide

from .models import Depense, GrilleFrais, Paiement, TypeFrais


def _style(formulaire):
    for champ in formulaire.fields.values():
        if isinstance(champ.widget, forms.Select):
            champ.widget.attrs["class"] = "form-select"
        elif not isinstance(champ.widget, forms.CheckboxInput):
            champ.widget.attrs["class"] = "form-control"
    annoter_relations_ajout_rapide(formulaire)


class FormulairePaiement(forms.Form):
    apprenant = forms.ModelChoiceField(label="Apprenant", queryset=Apprenant.objects.none())
    montant = forms.DecimalField(label="Montant", min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    date_paiement = forms.DateField(
        label="Date du paiement", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    motif = forms.CharField(label="Motif", max_length=180)
    mode = forms.ChoiceField(label="Mode de paiement", choices=Paiement.Mode.choices)
    reference = forms.CharField(label="Référence (facultatif)", max_length=80, required=False)

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["apprenant"].queryset = Apprenant.objects.filter(actif=True)
        if etablissement is not None:
            self.fields["apprenant"].queryset = self.fields["apprenant"].queryset.filter(
                etablissement=etablissement
            )
        _style(self)


class FormulaireDepense(forms.ModelForm):
    class Meta:
        model = Depense
        fields = ["montant", "date_depense", "categorie", "motif"]
        widgets = {
            "montant": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "date_depense": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireTypeFrais(forms.Form):
    nom = forms.CharField(label="Nom du type de frais", max_length=80)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireGrilleFrais(forms.ModelForm):
    class Meta:
        model = GrilleFrais
        fields = ["annee", "niveau", "type_frais", "montant", "nombre_echeances", "premiere_echeance"]
        widgets = {
            "montant": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "nombre_echeances": forms.NumberInput(attrs={"min": "1", "max": "12"}),
            "premiere_echeance": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["annee"].queryset = AnneeAcademique.objects.exclude(statut=AnneeAcademique.Statut.CLOTUREE)
        self.fields["niveau"].queryset = Niveau.objects.all()
        self.fields["type_frais"].queryset = TypeFrais.objects.filter(actif=True)
        if etablissement is not None:
            self.fields["annee"].queryset = self.fields["annee"].queryset.filter(etablissement=etablissement)
            self.fields["niveau"].queryset = self.fields["niveau"].queryset.filter(etablissement=etablissement)
            self.fields["type_frais"].queryset = self.fields["type_frais"].queryset.filter(etablissement=etablissement)
        _style(self)


class FormulaireEncaissement(forms.Form):
    montant = forms.DecimalField(label="Montant encaissé", min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    mode = forms.ChoiceField(label="Mode de paiement", choices=Paiement.Mode.choices)
    reference = forms.CharField(label="Référence (n° de chèque, de virement…)", max_length=80, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireAnnulation(forms.Form):
    motif = forms.CharField(label="Motif d'annulation", max_length=300)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireRemboursement(forms.Form):
    montant = forms.DecimalField(label="Montant à rembourser", min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    motif = forms.CharField(label="Motif du remboursement", max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulairePeriodeRapport(forms.Form):
    debut = forms.DateField(label="Du", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    fin = forms.DateField(label="Au", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aujourd_hui = date.today()
        if not self.is_bound:
            self.initial.setdefault("debut", aujourd_hui.replace(day=1))
            self.initial.setdefault("fin", aujourd_hui)
        _style(self)

    def clean(self):
        donnees = super().clean()
        debut, fin = donnees.get("debut"), donnees.get("fin")
        if debut and fin and debut > fin:
            self.add_error("fin", "La date de fin doit être postérieure ou égale à la date de début.")
        return donnees
