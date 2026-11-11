from django.core.exceptions import ValidationError
from django.db import models

from applications.academique.models import AnneeAcademique
from applications.noyau.models import ModeleEtablissement
from applications.pedagogie.models import AffectationEnseignant


JOURS = [
    (1, "Lundi"),
    (2, "Mardi"),
    (3, "Mercredi"),
    (4, "Jeudi"),
    (5, "Vendredi"),
    (6, "Samedi"),
    (7, "Dimanche"),
]


class Salle(ModeleEtablissement):
    nom = models.CharField("nom", max_length=60)
    capacite = models.PositiveSmallIntegerField("capacité", default=0, help_text="0 = non précisée")

    class Meta:
        verbose_name = "salle"
        verbose_name_plural = "salles"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "nom"], name="salle_nom_unique"),
        ]

    def __str__(self):
        return self.nom


class Creneau(ModeleEtablissement):
    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="creneaux")
    affectation = models.ForeignKey(
        AffectationEnseignant, on_delete=models.CASCADE, related_name="creneaux",
    )
    jour = models.PositiveSmallIntegerField("jour", choices=JOURS)
    heure_debut = models.TimeField("début")
    heure_fin = models.TimeField("fin")
    salle = models.ForeignKey(
        Salle, null=True, blank=True, on_delete=models.SET_NULL, related_name="creneaux",
    )

    class Meta:
        verbose_name = "créneau"
        verbose_name_plural = "créneaux"
        ordering = ["jour", "heure_debut"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(heure_fin__gt=models.F("heure_debut")),
                name="creneau_heures_coherentes",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_jour_display()} {self.heure_debut:%H:%M}-"
            f"{self.heure_fin:%H:%M} {self.affectation}"
        )

    def clean(self):
        super().clean()
        if self.heure_debut and self.heure_fin and self.heure_fin <= self.heure_debut:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
        if self.affectation_id and self.annee_id and self.affectation.matiere_niveau.annee_id != self.annee_id:
            raise ValidationError("L'affectation et le créneau doivent appartenir à la même année.")
