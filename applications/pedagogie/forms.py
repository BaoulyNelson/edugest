import json

from django import forms

from applications.academique.models import Classe
from applications.academique.services import annee_active
from applications.interface.forms import annoter_relations_ajout_rapide
from applications.noyau.models import Appartenance
from applications.noyau.permissions import CATALOGUE

from .models import MatiereNiveau, Matiere, RessourcePedagogique


class FormulaireInvitationEnseignant(forms.Form):
    email = forms.EmailField(label="Adresse e-mail", max_length=254)


def _style(formulaire):
    for champ in formulaire.fields.values():
        if isinstance(champ.widget, forms.CheckboxInput):
            champ.widget.attrs["class"] = "form-check-input"
        elif isinstance(champ.widget, forms.Select):
            champ.widget.attrs["class"] = "form-select"
        else:
            champ.widget.attrs["class"] = "form-control"
    annoter_relations_ajout_rapide(formulaire)


class FormulaireMatiere(forms.Form):
    nom = forms.CharField(label="Nom de la matière", max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class FormulaireMatiereNiveau(forms.Form):
    matiere = forms.ModelChoiceField(label="Matière", queryset=Matiere.objects.none())
    bareme = forms.DecimalField(label="Barème", min_value=1, max_digits=7, decimal_places=2,
                                help_text="Total de points de la matière dans ce niveau (ex. 100).")
    coefficient = forms.DecimalField(label="Coefficient", min_value=0.01, max_digits=5, decimal_places=2, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["matiere"].queryset = Matiere.objects.all()
        _style(self)


class FormulaireDerogation(forms.Form):
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    matiere_niveau = forms.ModelChoiceField(label="Matière", queryset=MatiereNiveau.objects.none())
    bareme = forms.DecimalField(label="Barème dérogatoire", required=False, min_value=1, max_digits=7, decimal_places=2)
    coefficient = forms.DecimalField(label="Coefficient dérogatoire", required=False, min_value=0.01, max_digits=5, decimal_places=2)
    exclue = forms.BooleanField(label="Matière non enseignée dans cette classe", required=False)

    def __init__(self, *args, niveau=None, annee=None, **kwargs):
        super().__init__(*args, **kwargs)
        if niveau is not None and annee is not None:
            self.fields["classe"].queryset = Classe.objects.filter(niveau=niveau, annee=annee)
            self.fields["matiere_niveau"].queryset = MatiereNiveau.objects.filter(niveau=niveau, annee=annee)
        _style(self)


class FormulaireAffectation(forms.Form):
    enseignant = forms.ModelChoiceField(label="Enseignant", queryset=Appartenance.objects.none())
    matiere_niveau = forms.ModelChoiceField(label="Matière et niveau", queryset=MatiereNiveau.objects.none())
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none(), required=False,
                                    empty_label="Tous les apprenants du niveau",
                                    help_text="Laissez vide pour un enseignement commun au niveau (universités).")

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        enseignants = [a.pk for a in Appartenance.objects.filter(actif=True).select_related("role", "utilisateur")
                       if "evaluations.saisir" in a.role.codes]
        self.fields["enseignant"].queryset = Appartenance.objects.filter(pk__in=enseignants).select_related("utilisateur")
        self.fields["enseignant"].label_from_instance = lambda a: a.utilisateur.nom_affiche
        annee = annee_active(etablissement) if etablissement else None
        if annee:
            self.fields["matiere_niveau"].queryset = MatiereNiveau.objects.filter(annee=annee).select_related("matiere", "niveau")
            self.fields["classe"].queryset = Classe.objects.filter(annee=annee)
        _style(self)
        self.fields["enseignant"].widget.attrs["data-inviter-enseignant"] = "true"


class FormulaireRessource(forms.ModelForm):
    class Meta:
        model = RessourcePedagogique
        fields = ["classe", "matiere_niveau", "titre", "description", "fichier"]

    def __init__(self, *args, paires=None, **kwargs):
        super().__init__(*args, **kwargs)
        paires = paires or set()
        classe_ids = {classe_id for classe_id, _ in paires}
        matiere_ids = {matiere_id for _, matiere_id in paires}
        self.fields["classe"].queryset = Classe.objects.filter(pk__in=classe_ids)
        self.fields["matiere_niveau"].queryset = MatiereNiveau.objects.filter(pk__in=matiere_ids)
        _style(self)


class FormulaireQuiz(forms.Form):
    titre = forms.CharField(label="Titre du quiz", max_length=150)
    description = forms.CharField(label="Consignes", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    matiere_niveau = forms.ModelChoiceField(label="Matière", queryset=MatiereNiveau.objects.none())
    date_limite = forms.DateTimeField(
        label="Date limite (facultative)", required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    nombre_tentatives_max = forms.IntegerField(label="Tentatives autorisées", min_value=1, max_value=10, initial=1)
    questions = forms.CharField(
        label="Questions et choix (JSON)",
        widget=forms.Textarea(attrs={"rows": 8, "spellcheck": "false"}),
        help_text='Format : [{"texte":"Question","choix":["A","B"],"bonne_reponse":0}] (index du bon choix, à partir de 0).',
    )

    def __init__(self, *args, paires=None, **kwargs):
        super().__init__(*args, **kwargs)
        paires = paires or set()
        self.fields["classe"].queryset = Classe.objects.filter(pk__in={c for c, _ in paires})
        self.fields["matiere_niveau"].queryset = MatiereNiveau.objects.filter(pk__in={m for _, m in paires})
        _style(self)

    def clean_questions(self):
        try:
            questions = json.loads(self.cleaned_data["questions"])
        except json.JSONDecodeError as erreur:
            raise forms.ValidationError("Le JSON des questions est invalide.") from erreur
        if not isinstance(questions, list):
            raise forms.ValidationError("Les questions doivent être présentées sous forme de liste JSON.")
        return questions
