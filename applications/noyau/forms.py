"""Formulaires de configuration de l'établissement et de gestion du noyau."""
from django import forms
from zoneinfo import available_timezones
from django.utils.translation import gettext_lazy as _

from .models import (
    ConfigurationPlateforme, Etablissement, ParametresEtablissement, TypeEtablissement, Utilisateur,
)


class FormulaireNouvelEspace(forms.Form):
    nom_etablissement = forms.CharField(label="Nom de l'établissement", max_length=200)
    type_etablissement = forms.ChoiceField(label="Type", choices=TypeEtablissement.choices,
                                           initial=TypeEtablissement.SCOLAIRE, widget=forms.RadioSelect)


class FormulaireProvisionnement(forms.Form):
    nom_etablissement = forms.CharField(label="Nom de l'établissement", max_length=200)
    type_etablissement = forms.ChoiceField(label="Type", choices=TypeEtablissement.choices)
    administrateur = forms.ModelChoiceField(
        label="Administrateur initial",
        queryset=Utilisateur.objects.none(),
        help_text="Choisissez un compte existant qui administrera ce nouvel espace.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type_etablissement"].widget = forms.Select(
            attrs={"class": "form-select"}, choices=self.fields["type_etablissement"].choices
        )
        self.fields["administrateur"].queryset = Utilisateur.objects.filter(is_active=True).order_by(
            "last_name", "first_name", "username"
        )
        self.fields["administrateur"].label_from_instance = (
            lambda utilisateur: f"{utilisateur.nom_affiche} · {utilisateur.email}"
        )
        for champ in self.fields.values():
            if not isinstance(champ.widget, forms.RadioSelect):
                champ.widget.attrs.setdefault("class", "form-control")


class FormulaireConfigurationPlateforme(forms.ModelForm):
    class Meta:
        model = ConfigurationPlateforme
        fields = [
                "nom", "nom_court", "slogan", "logo", "telephone", "email",
                "adresse", "site_web", "linkedin_url", "facebook_url", "instagram_url",
                "pied_de_page",
        ]
        labels = {
                "nom": _("Nom de la plateforme"),
                "nom_court": _("Nom court / sigle"),
                "slogan": _("Slogan"),
                "logo": _("Logo de la plateforme"),
                "telephone": _("Téléphone"),
                "email": _("Adresse e-mail"),
                "adresse": _("Adresse"),
                "site_web": _("Site web"),
                "linkedin_url": _("Page LinkedIn"),
                "facebook_url": _("Page Facebook"),
                "instagram_url": _("Compte Instagram"),
                "pied_de_page": _("Texte du pied de page"),
        }
        help_texts = {
                "nom_court": _("Nom concis utilisé dans l’en-tête lorsque le nom complet est trop long."),
                "logo": _("Logo utilisé dans les en-têtes; laissez vide pour afficher l’icône par défaut."),
                "pied_de_page": _("Ajoutez les informations de marque ou mentions utiles aux visiteurs."),
        }
        widgets = {
                "pied_de_page": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
                field.widget.attrs["class"] = "form-control"


class FormulaireIdentite(forms.ModelForm):
    fuseau_horaire = forms.ChoiceField(
        label=_("Fuseau horaire"),
        choices=tuple((zone, zone) for zone in sorted(available_timezones())),
        help_text=_("Les dates et heures affichées dans cet espace utiliseront ce fuseau. Les instants restent stockés en UTC."),
    )

    class Meta:
        model = Etablissement
        fields = [
            "nom", "nom_court", "slogan", "devise", "langue", "fuseau_horaire",
            "telephone", "email", "adresse", "site_web", "logo",
        ]
        labels = {
            "nom": _("Nom de l'établissement"),
            "nom_court": _("Nom court / sigle"),
            "slogan": _("Slogan"),
            "devise": _("Devise (code ISO, 3 lettres)"),
            "langue": _("Langue par défaut de l’établissement"),
            "telephone": _("Téléphone"),
            "email": _("Adresse e-mail"),
            "adresse": _("Adresse"),
            "site_web": _("Site web"),
            "logo": _("Logo (facultatif)"),
        }
        help_texts = {
            "nom_court": _("Exemple : CEMO pour Collège Éducation Moderne. Ce nom court est utilisé dans la navigation."),
            "devise": _("Exemple : HTG, XOF ou EUR. Elle sera affichée sur les factures et reçus."),
            "langue": _("Langue utilisée par défaut dans l’interface. Chaque utilisateur peut choisir une autre langue pour sa session."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["devise"].required = False
        self.fields["langue"].required = False
        self.fields["fuseau_horaire"].required = False

    def clean_devise(self):
        devise = (self.cleaned_data.get("devise") or self.instance.devise or "HTG").strip().upper()
        if len(devise) != 3 or not devise.isalpha() or not devise.isascii():
            raise forms.ValidationError("Saisissez un code ISO de devise composé de 3 lettres.")
        return devise

    def clean_langue(self):
        return self.cleaned_data.get("langue") or self.instance.langue or "fr"

    def clean_fuseau_horaire(self):
        return (
            self.cleaned_data.get("fuseau_horaire")
            or self.instance.fuseau_horaire
            or "America/Port-au-Prince"
        )


class FormulaireNotation(forms.ModelForm):
    class Meta:
        model = ParametresEtablissement
        fields = ["seuil_reussite_pct", "echelle_moyenne", "classement_autorise"]
        labels = {
            "seuil_reussite_pct": "Seuil de réussite (% du barème)",
            "echelle_moyenne": "Échelle d'affichage des moyennes",
            "classement_autorise": "Autoriser le classement des apprenants",
        }
        help_texts = {
            "seuil_reussite_pct": "Par défaut 50 % : réussite à partir de la moitié du barème.",
            "echelle_moyenne": "Les moyennes sont calculées en pourcentage puis affichées sur cette échelle (10, 20, 100…).",
        }


class FormulairePeriodes(forms.ModelForm):
    class Meta:
        model = ParametresEtablissement
        fields = ["nombre_periodes_par_annee"]
        labels = {"nombre_periodes_par_annee": "Nombre de périodes par année"}
        help_texts = {
            "nombre_periodes_par_annee": (
                "Valeur proposée automatiquement lors de la création d'une nouvelle année. "
                "Vous pourrez toujours l'ajuster pour une année précise."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre_periodes_par_annee"].min_value = 1
        self.fields["nombre_periodes_par_annee"].max_value = 12


class FormulaireRetention(forms.ModelForm):
    class Meta:
        model = ParametresEtablissement
        fields = ["retention_annees"]
        labels = {"retention_annees": "Durée de conservation (années)"}
        help_texts = {
            "retention_annees": (
                "Après cette durée depuis la dernière inscription, un dossier inactif peut être anonymisé. "
                "Les résultats et inscriptions historiques restent conservés."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["retention_annees"].min_value = 1
        self.fields["retention_annees"].max_value = 20


class FormulaireDemarrage(forms.Form):
    designation = forms.CharField(label="Année académique", max_length=20)
    date_debut = forms.DateField(label="Début", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_fin = forms.DateField(label="Fin", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    nombre_periodes = forms.IntegerField(label="Nombre de périodes", min_value=1, max_value=12,
                                         help_text="3 trimestres, 4 trimestres, 2 semestres…")
    niveaux_standards = forms.BooleanField(label="Créer les niveaux de la 7e année fondamentale à la philosophie", required=False, initial=True)
    classes_par_niveau = forms.IntegerField(label="Classes par niveau", min_value=0, max_value=8, initial=1,
                                            help_text="1 = classe A seulement, 2 = A et B…")

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        from datetime import date

        annee = date.today().year
        if not self.is_bound:
            self.initial.update({
                "designation": f"{annee}-{annee + 1}", "date_debut": date(annee, 9, 1), "date_fin": date(annee + 1, 6, 30),
                "nombre_periodes": (
                    etablissement.parametres.nombre_periodes_par_annee
                    if etablissement is not None
                    else 3
                ),
            })
        if etablissement is not None and etablissement.est_universitaire:
            del self.fields["niveaux_standards"]
            del self.fields["classes_par_niveau"]
