import uuid

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from applications.academique.models import Classe
from applications.apprenants.models import Inscription
from applications.noyau.models import Appartenance, ModeleEtablissement


class BadgeGenere(ModeleEtablissement):
    class Type(models.TextChoices):
        APPRENANT = "APPRENANT", "Apprenant"
        ENSEIGNANT = "ENSEIGNANT", "Enseignant"

    inscription = models.ForeignKey(
        Inscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="badges"
    )
    appartenance = models.ForeignKey(
        Appartenance, on_delete=models.SET_NULL, null=True, blank=True, related_name="badges"
    )
    classe = models.ForeignKey(Classe, on_delete=models.SET_NULL, null=True, blank=True, related_name="badges")
    type_badge = models.CharField(max_length=12, choices=Type.choices)
    jeton = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    genere_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "badge généré"
        verbose_name_plural = "badges générés"
        ordering = ["-cree_le", "-pk"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(type_badge="APPRENANT", inscription__isnull=False, appartenance__isnull=True)
                    | models.Q(type_badge="ENSEIGNANT", inscription__isnull=True, appartenance__isnull=False)
                ),
                name="badge_cible_coherente",
            )
        ]

    def clean(self):
        super().clean()
        if self.inscription_id and self.inscription.etablissement_id != self.etablissement_id:
            raise ValidationError("L'inscription du badge appartient à un autre établissement.")
        if self.appartenance_id and self.appartenance.etablissement_id != self.etablissement_id:
            raise ValidationError("L'appartenance du badge appartient à un autre établissement.")
        if self.classe_id and self.classe.etablissement_id != self.etablissement_id:
            raise ValidationError("La classe du badge appartient à un autre établissement.")
