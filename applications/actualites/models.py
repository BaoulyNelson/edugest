from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from applications.noyau.models import ModeleEtablissement


class Publication(ModeleEtablissement):
    class Type(models.TextChoices):
        ACTUALITE = "ACTUALITE", "Actualité"
        ANNONCE = "ANNONCE", "Annonce"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        PUBLIEE = "PUBLIEE", "Publiée"
        ARCHIVEE = "ARCHIVEE", "Archivée"

    type = models.CharField("type", max_length=10, choices=Type.choices)
    titre = models.CharField("titre", max_length=180)
    contenu = models.TextField("contenu")
    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    publiee_le = models.DateTimeField("date de publication", default=timezone.now)
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField("créée le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        verbose_name = "publication"
        verbose_name_plural = "publications"
        ordering = ["-publiee_le", "-pk"]
        indexes = [
            models.Index(fields=["etablissement", "statut", "publiee_le"], name="publication_visibilite_idx"),
        ]

    def __str__(self):
        return self.titre


class Evenement(ModeleEtablissement):
    class Statut(models.TextChoices):
        PLANIFIE = "PLANIFIE", "Planifié"
        ANNULE = "ANNULE", "Annulé"

    titre = models.CharField("titre", max_length=180)
    description = models.TextField("description", blank=True)
    debut = models.DateTimeField("début")
    fin = models.DateTimeField("fin")
    lieu = models.CharField("lieu", max_length=180, blank=True)
    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.PLANIFIE)
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "événement"
        verbose_name_plural = "événements"
        ordering = ["debut", "pk"]
        constraints = [
            models.CheckConstraint(check=models.Q(fin__gt=models.F("debut")), name="evenement_dates_coherentes"),
        ]
        indexes = [
            models.Index(fields=["etablissement", "statut", "debut"], name="evenement_visibilite_idx"),
        ]

    def __str__(self):
        return self.titre

    def clean(self):
        super().clean()
        if self.debut and self.fin and self.fin <= self.debut:
            raise ValidationError({"fin": "La fin doit être postérieure au début."})
