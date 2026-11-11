from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.noyau.models import ModeleEtablissement


class LotImportation(ModeleEtablissement):
    class Type(models.TextChoices):
        APPRENANTS = "APPRENANTS", "Apprenants"
        PERSONNEL = "PERSONNEL", "Personnel"

    type = models.CharField("type", max_length=15, choices=Type.choices)
    nom_fichier = models.CharField("fichier", max_length=255)
    lignes = models.JSONField("lignes à importer", default=list, blank=True)
    erreurs = models.JSONField("erreurs par ligne", default=list, blank=True)
    nombre_lignes = models.PositiveIntegerField("nombre de lignes", default=0)
    nombre_importe = models.PositiveIntegerField("nombre importé", default=0)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField("créé le", default=timezone.now)
    expire_le = models.DateTimeField("expire le")

    class Meta:
        verbose_name = "lot d'importation"
        verbose_name_plural = "lots d'importation"
        ordering = ["-cree_le", "-pk"]

    @property
    def nombre_erreurs(self):
        return len(self.erreurs)

    @property
    def nombre_valide(self):
        return len(self.lignes)
