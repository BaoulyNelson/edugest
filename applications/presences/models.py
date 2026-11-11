from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.academique.models import Classe
from applications.apprenants.models import Inscription
from applications.noyau.models import ModeleEtablissement


class AppelPresence(ModeleEtablissement):
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="appels_presence")
    date = models.DateField("date")
    enseignant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="appels_presence",
    )
    cle = models.CharField(max_length=80, editable=False)
    cree_le = models.DateTimeField("enregistré le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "appel de présence"
        verbose_name_plural = "appels de présence"
        ordering = ["-date", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "cle"], name="appel_presence_unique"),
        ]

    def save(self, *args, **kwargs):
        self.cle = f"{self.classe_id}:{self.date:%Y%m%d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.classe} · {self.date:%d/%m/%Y}"


class LignePresence(ModeleEtablissement):
    class Statut(models.TextChoices):
        PRESENT = "PRESENT", "Présent"
        ABSENT = "ABSENT", "Absent"
        RETARD = "RETARD", "En retard"
        JUSTIFIE = "JUSTIFIE", "Absence justifiée"

    appel = models.ForeignKey(AppelPresence, on_delete=models.CASCADE, related_name="lignes")
    inscription = models.ForeignKey(
        Inscription, on_delete=models.PROTECT, related_name="lignes_presence",
    )
    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.PRESENT)
    motif = models.CharField("motif", max_length=150, blank=True)

    class Meta:
        verbose_name = "ligne de présence"
        verbose_name_plural = "lignes de présence"
        constraints = [
            models.UniqueConstraint(fields=["appel", "inscription"], name="ligne_presence_unique"),
        ]

    def __str__(self):
        return f"{self.inscription.apprenant} · {self.get_statut_display()}"


class NotificationPresence(ModeleEtablissement):
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications_presence",
    )
    titre = models.CharField("titre", max_length=150)
    texte = models.CharField("message", max_length=300, blank=True)
    lue = models.BooleanField("lue", default=False)
    creee_le = models.DateTimeField("créée le", default=timezone.now)

    class Meta:
        verbose_name = "notification de présence"
        verbose_name_plural = "notifications de présence"
        ordering = ["-creee_le", "-pk"]

    def __str__(self):
        return self.titre
