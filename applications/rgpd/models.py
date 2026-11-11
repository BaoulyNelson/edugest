from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.apprenants.models import Apprenant
from applications.noyau.models import ModeleEtablissement


class Consentement(ModeleEtablissement):
    class Finalite(models.TextChoices):
        SCOLARITE = "SCOLARITE", "Gestion de la scolarité"
        IMAGE = "IMAGE", "Droit à l'image"
        COMMUNICATION = "COMMUNICATION", "Communications"
        AUTRE = "AUTRE", "Autre"

    apprenant = models.ForeignKey(Apprenant, on_delete=models.PROTECT, related_name="consentements")
    finalite = models.CharField("finalité", max_length=20, choices=Finalite.choices)
    accorde = models.BooleanField("accordé", default=False)
    note = models.CharField("précision", max_length=300, blank=True)
    enregistre_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField("enregistré le", default=timezone.now)

    class Meta:
        verbose_name = "consentement"
        verbose_name_plural = "consentements"
        ordering = ["-cree_le", "-pk"]

    def __str__(self):
        return f"{self.get_finalite_display()} · {self.apprenant}"


class DemandeRGPD(ModeleEtablissement):
    class Type(models.TextChoices):
        ACCES = "ACCES", "Accès ou copie des données"
        RECTIFICATION = "RECTIFICATION", "Rectification"
        EFFACEMENT = "EFFACEMENT", "Effacement ou anonymisation"
        OPPOSITION = "OPPOSITION", "Opposition au traitement"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        TRAITEE = "TRAITEE", "Traitée"
        REFUSEE = "REFUSEE", "Refusée"

    apprenant = models.ForeignKey(
        Apprenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes_rgpd"
    )
    demandeur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    type = models.CharField("type", max_length=20, choices=Type.choices)
    statut = models.CharField("statut", max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    details = models.TextField("détails", blank=True)
    reponse = models.TextField("réponse", blank=True)
    cree_le = models.DateTimeField("créée le", default=timezone.now)
    echeance = models.DateField("échéance")
    traitee_le = models.DateTimeField("traitée le", null=True, blank=True)

    class Meta:
        verbose_name = "demande de protection des données"
        verbose_name_plural = "demandes de protection des données"
        ordering = ["statut", "echeance", "-cree_le"]

    def __str__(self):
        return f"{self.get_type_display()} · {self.get_statut_display()}"
