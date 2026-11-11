"""Structure académique : années, périodes, facultés, programmes, niveaux, classes."""
from django.core.exceptions import ValidationError
from django.db import models

from applications.noyau.models import ModeleEtablissement


class AnneeAcademique(ModeleEtablissement):
    class Statut(models.TextChoices):
        PREPARATION = "PREPARATION", "En préparation"
        ACTIVE = "ACTIVE", "Active"
        CLOTUREE = "CLOTUREE", "Clôturée"

    designation = models.CharField("désignation", max_length=20, help_text="Exemple : 2026-2027")
    date_debut = models.DateField("date de début")
    date_fin = models.DateField("date de fin")
    statut = models.CharField("statut", max_length=20, choices=Statut.choices, default=Statut.PREPARATION)

    class Meta:
        verbose_name = "année académique"
        verbose_name_plural = "années académiques"
        ordering = ["-date_debut"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "designation"], name="unique_annee_par_etablissement"),
            models.CheckConstraint(check=models.Q(date_fin__gt=models.F("date_debut")), name="annee_dates_coherentes"),
        ]

    def __str__(self):
        return self.designation

    def clean(self):
        super().clean()
        if self.date_debut and self.date_fin and self.date_fin <= self.date_debut:
            raise ValidationError("La date de fin doit être postérieure à la date de début.")

    @property
    def est_active(self):
        return self.statut == self.Statut.ACTIVE


class Periode(ModeleEtablissement):
    class Statut(models.TextChoices):
        A_VENIR = "A_VENIR", "À venir"
        OUVERTE = "OUVERTE", "Ouverte"
        CLOTUREE = "CLOTUREE", "Clôturée"

    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="periodes", verbose_name="année")
    nom = models.CharField("nom", max_length=60)
    date_debut = models.DateField("date de début")
    date_fin = models.DateField("date de fin")
    ordre = models.PositiveSmallIntegerField("ordre")
    statut = models.CharField("statut", max_length=20, choices=Statut.choices, default=Statut.A_VENIR)
    saisie_ouverte = models.BooleanField("saisie des notes ouverte", default=False)

    class Meta:
        verbose_name = "période"
        verbose_name_plural = "périodes"
        ordering = ["annee", "ordre"]
        constraints = [
            models.UniqueConstraint(fields=["annee", "ordre"], name="unique_ordre_periode"),
            models.CheckConstraint(check=models.Q(date_fin__gte=models.F("date_debut")), name="periode_dates_coherentes"),
        ]

    def __str__(self):
        return f"{self.nom} ({self.annee})"


class SiteEtablissement(ModeleEtablissement):
    """Campus ou site physique d'un établissement multi-site."""

    nom = models.CharField("nom du site", max_length=120)
    code = models.CharField("code", max_length=20)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    actif = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "site"
        verbose_name_plural = "sites"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "code"], name="site_code_unique")
        ]

    def __str__(self):
        return self.nom


class PresetAcademique(ModeleEtablissement):
    """Structure pédagogique enregistrée pour être réutilisée lors d'une configuration."""

    nom = models.CharField("nom du preset", max_length=100)
    niveaux = models.JSONField("niveaux", default=list)
    actif = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "preset académique"
        verbose_name_plural = "presets académiques"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "nom"], name="preset_academique_nom_unique")
        ]

    def __str__(self):
        return self.nom

    def clean(self):
        super().clean()
        if not isinstance(self.niveaux, list) or not all(
            isinstance(niveau, str) and niveau.strip() for niveau in self.niveaux
        ):
            raise ValidationError("Les niveaux doivent être une liste de noms non vides.")


class Faculte(ModeleEtablissement):
    nom = models.CharField("nom", max_length=150)
    code = models.CharField("code", max_length=20, blank=True)

    class Meta:
        verbose_name = "faculté"
        verbose_name_plural = "facultés"
        ordering = ["nom"]
        constraints = [models.UniqueConstraint(fields=["etablissement", "nom"], name="unique_faculte")]

    def __str__(self):
        return self.nom


class Programme(ModeleEtablissement):
    faculte = models.ForeignKey(Faculte, on_delete=models.PROTECT, related_name="programmes", verbose_name="faculté")
    nom = models.CharField("nom", max_length=150)
    code = models.CharField("code", max_length=20, blank=True)

    class Meta:
        verbose_name = "programme"
        verbose_name_plural = "programmes"
        ordering = ["faculte__nom", "nom"]
        constraints = [models.UniqueConstraint(fields=["faculte", "nom"], name="unique_programme")]

    def __str__(self):
        return f"{self.nom} ({self.faculte})"

    def clean(self):
        super().clean()
        if self.faculte_id and self.faculte.etablissement_id != self.etablissement_id:
            raise ValidationError("La faculté et le programme doivent appartenir au même établissement.")


class Niveau(ModeleEtablissement):
    """Position dans le parcours. Pour une université, le niveau dépend d'un programme."""

    programme = models.ForeignKey(
        Programme, on_delete=models.PROTECT, null=True, blank=True, related_name="niveaux", verbose_name="programme"
    )
    nom = models.CharField("nom", max_length=100)
    ordre = models.PositiveSmallIntegerField("ordre", default=1)

    class Meta:
        verbose_name = "niveau"
        verbose_name_plural = "niveaux"
        ordering = ["programme__nom", "ordre", "nom"]

    def __str__(self):
        return self.nom if self.programme_id is None else f"{self.nom} - {self.programme.nom}"

    def clean(self):
        super().clean()
        if self.programme_id and self.programme.etablissement_id != self.etablissement_id:
            raise ValidationError("Le programme et le niveau doivent appartenir au même établissement.")
        niveaux = Niveau.sans_filtre.filter(
            etablissement_id=self.etablissement_id, programme_id=self.programme_id, nom=self.nom,
        )
        if self.pk:
            niveaux = niveaux.exclude(pk=self.pk)
        if self.nom and niveaux.exists():
            raise ValidationError({"nom": "Ce niveau existe déjà dans cet établissement et ce programme."})


class Classe(ModeleEtablissement):
    """Groupe pédagogique d'un niveau pour une année académique (écoles classiques)."""

    niveau = models.ForeignKey(Niveau, on_delete=models.PROTECT, related_name="classes", verbose_name="niveau")
    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="classes", verbose_name="année")
    site = models.ForeignKey(
        SiteEtablissement, on_delete=models.PROTECT, null=True, blank=True,
        related_name="classes", verbose_name="site",
    )
    nom = models.CharField("nom", max_length=50, help_text="Exemple : 7e A")
    effectif_max = models.PositiveSmallIntegerField("effectif maximal", null=True, blank=True)

    class Meta:
        verbose_name = "classe"
        verbose_name_plural = "classes"
        ordering = ["niveau__ordre", "nom"]
        constraints = [models.UniqueConstraint(fields=["niveau", "annee", "nom"], name="unique_classe")]

    def __str__(self):
        return self.nom

    def clean(self):
        super().clean()
        if self.niveau_id and self.niveau.etablissement_id != self.etablissement_id:
            raise ValidationError("Le niveau et la classe doivent appartenir au même établissement.")
        if self.annee_id and self.annee.etablissement_id != self.etablissement_id:
            raise ValidationError("L'année et la classe doivent appartenir au même établissement.")
        if self.site_id and self.site.etablissement_id != self.etablissement_id:
            raise ValidationError("Le site et la classe doivent appartenir au même établissement.")
