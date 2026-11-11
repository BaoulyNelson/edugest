from django import forms
from django.db.models import Q
from django.utils import timezone

from applications.academique.models import Classe, Niveau, Programme
from applications.academique.services import annee_active
from applications.interface.forms import annoter_relations_ajout_rapide
from applications.noyau.models import TypeEtablissement

from .models import (
    Apprenant, DecisionInscription, IncidentDisciplinaire, Inscription,
    LienResponsable, PieceInscription,
)


def _style(formulaire):
    for champ in formulaire.fields.values():
        if isinstance(champ.widget, forms.Select):
            champ.widget.attrs["class"] = "form-select"
        elif isinstance(champ.widget, forms.ClearableFileInput):
            champ.widget.attrs["class"] = "form-control"
        elif not isinstance(champ.widget, forms.CheckboxInput):
            champ.widget.attrs["class"] = "form-control"
    annoter_relations_ajout_rapide(formulaire)


class FormulaireApprenant(forms.Form):
    """Formulaire court : l'essentiel d'abord, le reste dans des sections facultatives."""

    nom = forms.CharField(label="Nom", max_length=100)
    prenoms = forms.CharField(label="Prénoms", max_length=150)
    sexe = forms.ChoiceField(label="Sexe", choices=Apprenant.Sexe.choices)
    date_naissance = forms.DateField(label="Date de naissance", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    lieu_naissance = forms.CharField(label="Lieu de naissance", max_length=150, required=False)
    email = forms.EmailField(label="Adresse e-mail de l'apprenant", required=False)
    telephone = forms.CharField(label="Téléphone", max_length=30, required=False)
    adresse = forms.CharField(label="Adresse", max_length=255, required=False)
    photo = forms.ImageField(label="Photo", required=False)
    responsable_nom = forms.CharField(label="Nom du responsable", max_length=100, required=False)
    responsable_prenoms = forms.CharField(label="Prénoms du responsable", max_length=150, required=False)
    responsable_telephone = forms.CharField(label="Téléphone du responsable", max_length=30, required=False)
    responsable_email = forms.EmailField(label="E-mail du responsable", required=False)
    responsable_lien = forms.ChoiceField(label="Lien", choices=LienResponsable.Lien.choices, required=False, initial="TUTEUR")

    def __init__(self, *args, etablissement=None, instance=None, **kwargs):
        self.instance = instance
        initial = dict(kwargs.pop("initial", {}) or {})
        if instance is not None:
            initial.update({
                "nom": instance.nom,
                "prenoms": instance.prenoms,
                "sexe": instance.sexe,
                "date_naissance": instance.date_naissance,
                "lieu_naissance": instance.lieu_naissance,
                "email": instance.email,
                "telephone": instance.telephone,
                "adresse": instance.adresse,
            })
            lien = instance.liens_responsables.select_related("responsable").filter(principal=True).first()
            if lien is not None:
                initial.update({
                    "responsable_nom": lien.responsable.nom,
                    "responsable_prenoms": lien.responsable.prenoms,
                    "responsable_telephone": lien.responsable.telephone,
                    "responsable_email": lien.responsable.email,
                    "responsable_lien": lien.lien,
                })
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        if etablissement is not None and etablissement.type != TypeEtablissement.SCOLAIRE:
            for champ in (
                "responsable_nom", "responsable_prenoms", "responsable_telephone",
                "responsable_email", "responsable_lien",
            ):
                del self.fields[champ]
        _style(self)

    def clean(self):
        donnees = super().clean()
        champs_responsable = (
            donnees.get("responsable_prenoms"), donnees.get("responsable_telephone"),
            donnees.get("responsable_email"),
        )
        if any(champs_responsable) and not donnees.get("responsable_nom"):
            self.add_error("responsable_nom", "Le nom du responsable est obligatoire si ses coordonnées sont renseignées.")
        return donnees

    def clean_date_naissance(self):
        date_naissance = self.cleaned_data["date_naissance"]
        if date_naissance > timezone.localdate():
            raise forms.ValidationError("La date de naissance ne peut pas être dans le futur.")
        return date_naissance


class FormulaireInscription(forms.Form):
    apprenant = forms.ModelChoiceField(label="Apprenant", queryset=Apprenant.objects.none())
    niveau = forms.ModelChoiceField(label="Niveau demandé", queryset=Niveau.objects.none())
    programme = forms.ModelChoiceField(label="Programme", queryset=Programme.objects.none(), required=False)
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none(), required=False,
                                    help_text="Facultatif : peut être précisée plus tard.", empty_label="À déterminer")
    type_inscription = forms.ChoiceField(label="Type", choices=Inscription.Type.choices, initial="NOUVELLE")
    motif_correction = forms.CharField(
        label="Motif de la correction", required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, etablissement=None, inscription=None, correction_validee=False, **kwargs):
        self.inscription = inscription
        self.correction_validee = correction_validee
        if etablissement is None and inscription is not None:
            etablissement = inscription.etablissement
        initial = dict(kwargs.pop("initial", {}) or {})
        if inscription is not None:
            initial.update({
                "apprenant": inscription.apprenant_id,
                "niveau": inscription.niveau_id,
                "type_inscription": inscription.type,
                "classe": inscription.classe_id,
                "programme": inscription.programme_id,
            })
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        apprenants = Apprenant.objects.filter(actif=True)
        if inscription is not None:
            apprenants = Apprenant.objects.filter(
                Q(actif=True) | Q(pk=inscription.apprenant_id)
            )
        self.fields["apprenant"].queryset = apprenants
        self.fields["niveau"].queryset = Niveau.objects.select_related("programme")
        annee = inscription.annee if inscription is not None else (
            annee_active(etablissement) if etablissement else None
        )
        if etablissement is not None and etablissement.est_universitaire:
            self.fields["programme"].queryset = Programme.objects.all()
            self.fields["programme"].required = True
            del self.fields["classe"]
        else:
            del self.fields["programme"]
            self.fields["classe"].queryset = Classe.objects.filter(annee=annee) if annee else Classe.objects.none()
        if correction_validee:
            self.fields["apprenant"].disabled = True
            self.fields["type_inscription"].disabled = True
            self.fields["motif_correction"].required = True
        _style(self)


class FormulaireDecision(forms.Form):
    decision = forms.ChoiceField(label="Décision", choices=DecisionInscription.Decision.choices)
    motif = forms.CharField(label="Motif", required=False, widget=forms.Textarea(attrs={"rows": 2}),
                            help_text="Obligatoire pour rejeter ou demander une correction.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireFinAnnee(forms.Form):
    decision = forms.ChoiceField(label="Décision de fin d'année", choices=Inscription.DecisionFinAnnee.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireChangementClasse(forms.Form):
    classe = forms.ModelChoiceField(label="Nouvelle classe", queryset=Classe.objects.none())

    def __init__(self, *args, inscription=None, **kwargs):
        super().__init__(*args, **kwargs)
        if inscription is not None:
            self.fields["classe"].queryset = Classe.objects.filter(niveau=inscription.niveau, annee=inscription.annee)
        _style(self)


class FormulairePiece(forms.ModelForm):
    class Meta:
        model = PieceInscription
        fields = ["libelle", "fichier"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireIncidentDisciplinaire(forms.Form):
    date_incident = forms.DateField(
        label="Date de l'incident", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    categorie = forms.ChoiceField(label="Catégorie", choices=IncidentDisciplinaire.Categorie.choices)
    description = forms.CharField(label="Description", widget=forms.Textarea(attrs={"rows": 3}))
    mesure = forms.CharField(label="Mesure ou suivi", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    confidentiel = forms.BooleanField(label="Incident confidentiel", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
