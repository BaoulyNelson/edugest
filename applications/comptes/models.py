from django.db import models
from django.utils import timezone


class TentativeConnexion(models.Model):
    """Compteur de tentatives ratées, indexé par un identifiant pseudonymisé."""

    cle = models.CharField(max_length=64, unique=True)
    nombre = models.PositiveSmallIntegerField(default=0)
    derniere_tentative = models.DateTimeField(default=timezone.now)
    bloquee_jusqua = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "compteur de tentatives de connexion"
        verbose_name_plural = "compteurs de tentatives de connexion"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def est_bloquee(self):
        return bool(self.bloquee_jusqua and self.bloquee_jusqua > timezone.now())