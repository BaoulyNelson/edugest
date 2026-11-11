"""Dossiers permanents des apprenants et inscriptions annuelles."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from applications.academique.models import AnneeAcademique, Classe, Niveau, Programme
from applications.noyau.models import ModeleEtablissement


class Apprenant(ModeleEtablissement):
    """Dossier permanent : enregistré une seule fois, quel que soit le nombre d'inscriptions."""

    class Sexe(models.TextChoices):
        MASCULIN = "M", "Masculin"
        FEMININ = "F", "Féminin"

    matricule = models.CharField("matricule", max_length=30, editable=False)
    nom = models.CharField("nom", max_length=100)
    prenoms = models.CharField("prénoms", max_length=150)
    sexe = models.CharField("sexe", max_length=1, choices=Sexe.choices, blank=True)
    date_naissance = models.DateField("date de naissance")
    lieu_naissance = models.CharField("lieu de naissance", max_length=150, blank=True)
    email = models.EmailField("adresse e-mail", blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    photo = models.ImageField("photo", upload_to="apprenants/", blank=True)
    actif = models.BooleanField("actif", default=True)
    anonymise = models.BooleanField("données anonymisées", default=False)
    anonymise_le = models.DateTimeField("anonymisé le", null=True, blank=True)
    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dossier_apprenant", verbose_name="compte utilisateur",
    )

    class Meta:
        verbose_name = "apprenant"
        verbose_name_plural = "apprenants"
        ordering = ["nom", "prenoms"]
        constraints = [models.UniqueConstraint(fields=["etablissement", "matricule"], name="unique_matricule")]

    def clean(self):
        super().clean()
        if self.date_naissance and self.date_naissance > timezone.localdate():
            raise ValidationError({"date_naissance": "La date de naissance ne peut pas être dans le futur."})

    def __str__(self):
        return f"{self.nom} {self.prenoms}"


class ResponsableLegal(ModeleEtablissement):
    nom = models.CharField("nom", max_length=100)
    prenoms = models.CharField("prénoms", max_length=150, blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    email = models.EmailField("e-mail", blank=True)
    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dossier_responsable", verbose_name="compte utilisateur",
    )

    class Meta:
        verbose_name = "responsable légal"
        verbose_name_plural = "responsables légaux"
        ordering = ["nom", "prenoms"]

    def __str__(self):
        return f"{self.nom} {self.prenoms}".strip()


class LienResponsable(ModeleEtablissement):
    class Lien(models.TextChoices):
        PERE = "PERE", "Père"
        MERE = "MERE", "Mère"
        TUTEUR = "TUTEUR", "Tuteur"
        AUTRE = "AUTRE", "Autre"

    apprenant = models.ForeignKey(Apprenant, on_delete=models.CASCADE, related_name="liens_responsables")
    responsable = models.ForeignKey(ResponsableLegal, on_delete=models.CASCADE, related_name="liens_apprenants")
    lien = models.CharField("lien", max_length=10, choices=Lien.choices, default=Lien.TUTEUR)
    principal = models.BooleanField("responsable principal", default=False)

    class Meta:
        verbose_name = "lien apprenant-responsable"
        verbose_name_plural = "liens apprenant-responsable"
        constraints = [models.UniqueConstraint(fields=["apprenant", "responsable"], name="unique_lien_responsable")]


class Inscription(ModeleEtablissement):
    class Type(models.TextChoices):
        NOUVELLE = "NOUVELLE", "Nouvelle inscription"
        REINSCRIPTION = "REINSCRIPTION", "Réinscription"
        REDOUBLEMENT = "REDOUBLEMENT", "Redoublement"
        TRANSFERT = "TRANSFERT", "Transfert"
        REPRISE = "REPRISE", "Reprise des études"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        CORRECTION_DEMANDEE = "CORRECTION_DEMANDEE", "Correction demandée"
        VALIDEE = "VALIDEE", "Validée"
        REJETEE = "REJETEE", "Rejetée"
        ANNULEE = "ANNULEE", "Annulée"

    class DecisionFinAnnee(models.TextChoices):
        PASSAGE = "PASSAGE", "Passage au niveau supérieur"
        REDOUBLEMENT = "REDOUBLEMENT", "Redoublement"
        DIPLOME = "DIPLOME", "Diplômé"
        ABANDON = "ABANDON", "Abandon"
        INTERRUPTION = "INTERRUPTION", "Interruption du parcours"

    STATUTS_EN_COURS = ("EN_ATTENTE", "CORRECTION_DEMANDEE", "VALIDEE")

    apprenant = models.ForeignKey(Apprenant, on_delete=models.PROTECT, related_name="inscriptions", verbose_name="apprenant")
    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="inscriptions", verbose_name="année")
    type = models.CharField("type", max_length=15, choices=Type.choices, default=Type.NOUVELLE)
    statut = models.CharField("statut", max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    niveau = models.ForeignKey(Niveau, on_delete=models.PROTECT, related_name="inscriptions", verbose_name="niveau")
    classe = models.ForeignKey(
        Classe, on_delete=models.PROTECT, null=True, blank=True, related_name="inscriptions", verbose_name="classe"
    )
    programme = models.ForeignKey(
        Programme, on_delete=models.PROTECT, null=True, blank=True, related_name="inscriptions", verbose_name="programme"
    )
    decision_fin_annee = models.CharField(
        "décision de fin d'année", max_length=15, choices=DecisionFinAnnee.choices, blank=True
    )
    creee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    date_demande = models.DateTimeField("date de la demande", auto_now_add=True)

    class Meta:
        verbose_name = "inscription"
        verbose_name_plural = "inscriptions"
        ordering = ["-date_demande"]

    def __str__(self):
        return f"{self.apprenant} - {self.annee}"

    @property
    def est_active(self):
        """Seule une inscription validée est une inscription académique active."""
        return self.statut == self.Statut.VALIDEE

    @property
    def faculte(self):
        return self.programme.faculte if self.programme_id else None

    def clean(self):
        super().clean()
        relations = (
            (self.apprenant_id, self.apprenant, "L'apprenant"),
            (self.annee_id, self.annee, "L'année"),
            (self.niveau_id, self.niveau, "Le niveau"),
            (self.classe_id, self.classe, "La classe"),
            (self.programme_id, self.programme, "Le programme"),
        )
        for identifiant, objet, libelle in relations:
            if identifiant and objet.etablissement_id != self.etablissement_id:
                raise ValidationError(f"{libelle} et l'inscription doivent appartenir au même établissement.")
        if self.classe_id and (
            self.classe.niveau_id != self.niveau_id or self.classe.annee_id != self.annee_id
        ):
            raise ValidationError("La classe doit correspondre au niveau et à l'année de l'inscription.")
        if self.programme_id and self.niveau_id and self.niveau.programme_id != self.programme_id:
            raise ValidationError("Le programme doit correspondre au niveau de l'inscription.")
        if (
            self.apprenant_id and self.annee_id
            and self.statut in self.STATUTS_EN_COURS
        ):
            inscriptions = Inscription.sans_filtre.filter(
                apprenant_id=self.apprenant_id, annee_id=self.annee_id,
                statut__in=self.STATUTS_EN_COURS,
            )
            if self.pk:
                inscriptions = inscriptions.exclude(pk=self.pk)
            if inscriptions.exists():
                raise ValidationError("Cet apprenant a déjà une inscription en cours pour cette année.")


class DecisionInscription(ModeleEtablissement):
    class Decision(models.TextChoices):
        VALIDER = "VALIDER", "Validée"
        REJETER = "REJETER", "Rejetée"
        DEMANDER_CORRECTION = "DEMANDER_CORRECTION", "Correction demandée"

    inscription = models.ForeignKey(Inscription, on_delete=models.CASCADE, related_name="decisions")
    decision = models.CharField("décision", max_length=20, choices=Decision.choices)
    motif = models.TextField("motif", blank=True)
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    date = models.DateTimeField("date", auto_now_add=True)

    class Meta:
        verbose_name = "décision d'inscription"
        verbose_name_plural = "décisions d'inscription"
        ordering = ["-date", "-id"]


class PieceInscription(ModeleEtablissement):
    inscription = models.ForeignKey(Inscription, on_delete=models.CASCADE, related_name="pieces")
    libelle = models.CharField("libellé", max_length=150)
    fichier = models.FileField("fichier", upload_to="pieces/")

    class Meta:
        verbose_name = "pièce d'inscription"
        verbose_name_plural = "pièces d'inscription"


class IncidentDisciplinaire(ModeleEtablissement):
    class Categorie(models.TextChoices):
        COMPORTEMENT = "COMPORTEMENT", "Comportement"
        ABSENCE = "ABSENCE", "Absence"
        RETARD = "RETARD", "Retard"
        AUTRE = "AUTRE", "Autre"

    inscription = models.ForeignKey(
        Inscription, on_delete=models.PROTECT, related_name="incidents_disciplinaires"
    )
    date_incident = models.DateField("date de l'incident")
    categorie = models.CharField("catégorie", max_length=15, choices=Categorie.choices)
    description = models.TextField("description")
    mesure = models.TextField("mesure ou suivi", blank=True)
    confidentiel = models.BooleanField("confidentiel", default=False)
    enregistre_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField("enregistré le", auto_now_add=True)

    class Meta:
        verbose_name = "incident disciplinaire"
        verbose_name_plural = "incidents disciplinaires"
        ordering = ["-date_incident", "-pk"]

    def __str__(self):
        return f"{self.get_categorie_display()} · {self.inscription.apprenant}"
