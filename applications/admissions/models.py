import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.academique.models import AnneeAcademique, Classe
from applications.apprenants.models import Apprenant, Inscription
from applications.noyau.models import ModeleEtablissement


class Candidature(ModeleEtablissement):
    class Statut(models.TextChoices):
        RECUE = "RECUE", "Reçue"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REFUSEE = "REFUSEE", "Refusée"

    reference = models.UUIDField("référence", default=uuid.uuid4, unique=True, editable=False)
    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="candidatures")
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="candidatures")
    nom = models.CharField("nom de l'enfant", max_length=100)
    prenoms = models.CharField("prénoms de l'enfant", max_length=150)
    sexe = models.CharField("sexe", max_length=1, choices=Apprenant.Sexe.choices, blank=True)
    date_naissance = models.DateField("date de naissance")
    lieu_naissance = models.CharField("lieu de naissance", max_length=150, blank=True)
    nom_parent = models.CharField("nom du parent ou tuteur", max_length=150)
    telephone_parent = models.CharField("téléphone du parent", max_length=30)
    email_parent = models.EmailField("courriel du parent")
    message = models.CharField("message à la direction", max_length=2000, blank=True)
    consentement_donnees = models.BooleanField("consentement au traitement des données", default=False)
    consentement_le = models.DateTimeField("consentement donné le", null=True, blank=True)
    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.RECUE)
    inscription_creee = models.ForeignKey(
        Inscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="candidature_origine"
    )
    apprenant_cree = models.ForeignKey(
        Apprenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="candidature_origine"
    )
    date_creation = models.DateTimeField("déposée le", auto_now_add=True)
    traitee_le = models.DateTimeField("traitée le", null=True, blank=True)
    traitee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    motif_decision = models.CharField("motif de décision", max_length=500, blank=True)

    class Meta:
        verbose_name = "candidature"
        verbose_name_plural = "candidatures"
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.prenoms} {self.nom} — {self.classe}"
