"""Formulaires de connexion, d'inscription et de rattachement des comptes."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from applications.apprenants.models import Apprenant, ResponsableLegal
from applications.interface.forms import annoter_relations_ajout_rapide
from applications.noyau.models import Role, TypeEtablissement


class FormulaireConnexion(AuthenticationForm):
    username = forms.CharField(
        label="Nom d’utilisateur ou adresse e-mail",
        widget=forms.TextInput(attrs={
            "autocomplete": "username", "autofocus": True,
            "placeholder": "Votre nom d’utilisateur ou adresse e-mail",
        }),
    )
    password = forms.CharField(
        label="Mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password", "placeholder": "Votre mot de passe",
        }),
    )
    error_messages = {
        "invalid_login": "Nom d’utilisateur/adresse e-mail ou mot de passe incorrect.",
        "inactive": "Ce compte est désactivé.",
    }


class FormulaireCompte(forms.Form):
    prenom = forms.CharField(
        label="Prénom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"})
    )
    nom = forms.CharField(
        label="Nom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"})
    )
    username = forms.CharField(
        label="Nom d’utilisateur",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
        validators=get_user_model()._meta.get_field("username").validators,
        help_text="Vous pourrez vous connecter avec votre nom d’utilisateur ou votre adresse e-mail.",
    )
    email = forms.EmailField(label="Adresse e-mail", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    mot_de_passe = forms.CharField(
        label="Mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="8 caractères minimum, difficile à deviner.",
    )

    def clean_mot_de_passe(self):
        mot_de_passe = self.cleaned_data["mot_de_passe"]
        validate_password(mot_de_passe)
        return mot_de_passe

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        utilisateur = get_user_model()
        if utilisateur.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d’utilisateur est déjà utilisé.")
        return username


class FormulaireInscriptionEspace(FormulaireCompte):
    nom_etablissement = forms.CharField(
        label="Nom de votre établissement",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ex. Collège Saint-Louis"}),
    )
    type_etablissement = forms.ChoiceField(
        label="Type d'établissement",
        choices=TypeEtablissement.choices,
        initial=TypeEtablissement.SCOLAIRE,
        widget=forms.RadioSelect,
    )
    plan = forms.ChoiceField(label="Formule choisie")
    field_order = ["nom_etablissement", "type_etablissement", "plan", "prenom", "nom", "username", "email", "mot_de_passe"]

    def __init__(self, *args, **kwargs):
        from applications.noyau import saas

        super().__init__(*args, **kwargs)
        choix_plans = []
        for code in saas.PLANS_PAR_DEFAUT:
            plan = saas.obtenir_plan(code)
            prix = f"{plan.prix_mensuel:g} $/mois" if plan.prix_mensuel else "Gratuit"
            choix_plans.append((code, f"{plan.nom} — {prix}"))
        self.fields["plan"].choices = choix_plans
        self.fields["plan"].help_text = "Vous pourrez modifier votre formule depuis la gestion de l’abonnement."


class FormulaireInvitation(forms.Form):
    email = forms.EmailField(
        label="Adresse e-mail de la personne",
        widget=forms.EmailInput(attrs={"placeholder": "prenom.nom@exemple.com"}),
    )
    role = forms.ModelChoiceField(label="Rôle", queryset=Role.objects.none())
    apprenant = forms.ModelChoiceField(
        label="Dossier de l'apprenant (pour le rôle Apprenant)",
        queryset=Apprenant.objects.none(),
        required=False,
        empty_label="Aucun dossier sélectionné",
    )
    responsable = forms.ModelChoiceField(
        label="Dossier du responsable (pour le rôle Parent)",
        queryset=ResponsableLegal.objects.none(),
        required=False,
        empty_label="Aucun dossier sélectionné",
    )

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.all()
        self.fields["apprenant"].queryset = Apprenant.objects.filter(actif=True)
        self.fields["responsable"].queryset = ResponsableLegal.objects.all()
        if etablissement is not None:
            if etablissement.type != TypeEtablissement.SCOLAIRE:
                self.fields["role"].queryset = self.fields["role"].queryset.exclude(nom="Parent")
                del self.fields["responsable"]
            self.fields["apprenant"].queryset = self.fields["apprenant"].queryset.filter(
                etablissement=etablissement
            )
            if "responsable" in self.fields:
                self.fields["responsable"].queryset = self.fields["responsable"].queryset.filter(
                    etablissement=etablissement
                )
        annoter_relations_ajout_rapide(self)

    def clean(self):
        donnees = super().clean()
        role = donnees.get("role")
        apprenant = donnees.get("apprenant")
        responsable = donnees.get("responsable")
        email = (donnees.get("email") or "").strip().casefold()
        if role and role.nom == "Apprenant":
            if not apprenant:
                self.add_error("apprenant", "Sélectionnez le dossier à rattacher au compte.")
            elif apprenant.utilisateur_id:
                self.add_error("apprenant", "Ce dossier est déjà associé à un compte.")
            elif apprenant.email and apprenant.email.casefold() != email:
                self.add_error("email", "L'adresse doit correspondre à celle du dossier apprenant.")
            if responsable:
                self.add_error("responsable", "Un compte Apprenant ne peut pas être lié à un dossier parent.")
        elif role and role.nom == "Parent":
            if not responsable:
                self.add_error("responsable", "Sélectionnez le dossier à rattacher au compte.")
            elif responsable.utilisateur_id:
                self.add_error("responsable", "Ce dossier est déjà associé à un compte.")
            elif responsable.email.casefold() != email:
                self.add_error("email", "L'adresse doit correspondre à celle du dossier du responsable.")
            if apprenant:
                self.add_error("apprenant", "Un compte Parent ne peut pas être lié directement à un dossier apprenant.")
        elif apprenant or responsable:
            self.add_error(None, "Les dossiers ne peuvent être liés qu'aux rôles Apprenant et Parent.")
        return donnees


class FormulaireCompteInvite(forms.Form):
    prenom = forms.CharField(label="Prénom", max_length=150)
    nom = forms.CharField(label="Nom", max_length=150)
    username = forms.CharField(
        label="Nom d’utilisateur",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
        validators=get_user_model()._meta.get_field("username").validators,
    )
    mot_de_passe = forms.CharField(
        label="Choisissez votre mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="8 caractères minimum, difficile à deviner.",
    )

    def clean_mot_de_passe(self):
        validate_password(self.cleaned_data["mot_de_passe"])
        return self.cleaned_data["mot_de_passe"]

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        utilisateur = get_user_model()
        if utilisateur.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d’utilisateur est déjà utilisé.")
        return username