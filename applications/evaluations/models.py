"""Évaluations flexibles, notes et résultats par période."""
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from applications.academique.models import Periode
from applications.apprenants.models import Inscription
from applications.noyau.models import ModeleEtablissement
from applications.pedagogie.models import AffectationEnseignant, MatiereNiveau
from applications.cahier.stockage import StockagePrive


def chemin_document_resultat(instance, nom_fichier):
    extension = os.path.splitext(nom_fichier)[1].lower() or ".pdf"
    return (
        f"etablissements/{instance.etablissement_id}/resultats/"
        f"{instance.inscription_id}/{instance.periode_id}/{uuid.uuid4().hex}{extension}"
    )


class ConfigurationEvaluation(ModeleEtablissement):
    """Organisation de l'évaluation d'une matière, pour une affectation et une période."""

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        VALIDEE = "VALIDEE", "Validée"
        VERROUILLEE = "VERROUILLEE", "Verrouillée"

    affectation = models.ForeignKey(AffectationEnseignant, on_delete=models.PROTECT, related_name="configurations")
    periode = models.ForeignKey(Periode, on_delete=models.PROTECT, related_name="configurations")
    statut = models.CharField("statut", max_length=12, choices=Statut.choices, default=Statut.BROUILLON)

    class Meta:
        verbose_name = "configuration d'évaluation"
        verbose_name_plural = "configurations d'évaluation"
        constraints = [models.UniqueConstraint(fields=["affectation", "periode"], name="unique_configuration")]

    def __str__(self):
        return f"{self.affectation} - {self.periode.nom}"


class ComposanteEvaluation(ModeleEtablissement):
    configuration = models.ForeignKey(ConfigurationEvaluation, on_delete=models.CASCADE, related_name="composantes")
    intitule = models.CharField("intitulé", max_length=100)
    bareme = models.DecimalField("barème", max_digits=7, decimal_places=2)
    ordre = models.PositiveSmallIntegerField("ordre", default=1)

    class Meta:
        verbose_name = "composante d'évaluation"
        verbose_name_plural = "composantes d'évaluation"
        ordering = ["configuration", "ordre"]
        constraints = [models.CheckConstraint(check=models.Q(bareme__gt=0), name="composante_bareme_positif")]

    def __str__(self):
        return f"{self.intitule} ({self.bareme})"


class Note(ModeleEtablissement):
    class Etat(models.TextChoices):
        SAISIE = "SAISIE", "Note saisie"
        ABSENT = "ABSENT", "Absent"
        DISPENSE = "DISPENSE", "Dispensé"
        NON_RENSEIGNEE = "NON_RENSEIGNEE", "Non renseignée"

    composante = models.ForeignKey(ComposanteEvaluation, on_delete=models.CASCADE, related_name="notes")
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="notes")
    valeur = models.DecimalField("valeur", max_digits=7, decimal_places=2, null=True, blank=True)
    etat = models.CharField("état", max_length=15, choices=Etat.choices, default=Etat.SAISIE)

    class Meta:
        verbose_name = "note"
        verbose_name_plural = "notes"
        constraints = [
            models.UniqueConstraint(fields=["composante", "inscription"], name="unique_note"),
            models.CheckConstraint(
                check=models.Q(etat="SAISIE", valeur__isnull=False)
                | (~models.Q(etat="SAISIE") & models.Q(valeur__isnull=True)),
                name="note_valeur_coherente_avec_etat",
            ),
        ]


class HistoriqueNote(ModeleEtablissement):
    """Trace immuable des créations et changements apportés à une note."""

    note = models.ForeignKey(Note, on_delete=models.SET_NULL, null=True, related_name="historique")
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="historique_notes")
    composante = models.ForeignKey(
        ComposanteEvaluation, on_delete=models.PROTECT, related_name="historique_notes"
    )
    ancienne_valeur = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    ancien_etat = models.CharField(max_length=15, blank=True)
    nouvelle_valeur = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    nouvel_etat = models.CharField(max_length=15)
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    motif = models.TextField(blank=True)
    date_modification = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "historique de note"
        verbose_name_plural = "historiques de notes"
        ordering = ["-date_modification", "-pk"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("L'historique des notes ne peut pas être modifié.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("L'historique des notes ne peut pas être supprimé.")


class ResultatPeriode(ModeleEtablissement):
    class Statut(models.TextChoices):
        REUSSI = "REUSSI", "Réussi"
        ECHEC = "ECHEC", "Échec"
        INCOMPLET = "INCOMPLET", "Incomplet"
        DISPENSE = "DISPENSE", "Dispensé"

    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="resultats")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.PROTECT, related_name="resultats")
    periode = models.ForeignKey(Periode, on_delete=models.PROTECT, related_name="resultats")
    total = models.DecimalField("total", max_digits=8, decimal_places=2, default=0)
    bareme_applique = models.DecimalField("barème pris en compte", max_digits=8, decimal_places=2, default=0)
    pourcentage = models.DecimalField("pourcentage", max_digits=6, decimal_places=2, null=True, blank=True)
    statut = models.CharField("statut", max_length=10, choices=Statut.choices)
    publie = models.BooleanField("publié", default=False)
    date_publication = models.DateTimeField("date de publication", null=True, blank=True)

    class Meta:
        verbose_name = "résultat de période"
        verbose_name_plural = "résultats de période"
        constraints = [
            models.UniqueConstraint(fields=["inscription", "matiere_niveau", "periode"], name="unique_resultat")
        ]


class DocumentResultat(ModeleEtablissement):
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="documents_resultat")
    periode = models.ForeignKey(Periode, on_delete=models.PROTECT, related_name="documents_resultat")
    version = models.PositiveSmallIntegerField()
    fichier = models.FileField(
        upload_to=chemin_document_resultat, storage=StockagePrive(), blank=True
    )
    empreinte_sha256 = models.CharField(max_length=64)
    instantane = models.JSONField(default=dict, blank=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField(default=timezone.now, editable=False)
    revoque_le = models.DateTimeField(null=True, blank=True)
    motif_revocation = models.TextField(blank=True)

    class Meta:
        verbose_name = "document de résultats"
        verbose_name_plural = "documents de résultats"
        ordering = ["-version", "-cree_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["inscription", "periode", "version"], name="document_resultat_version_unique"
            ),
            models.CheckConstraint(check=models.Q(version__gte=1), name="document_resultat_version_positive"),
        ]

    @property
    def est_valide(self):
        return self.revoque_le is None

    def save(self, *args, **kwargs):
        if self.pk:
            original = DocumentResultat.sans_filtre.get(pk=self.pk)
            immuables = (
                "etablissement_id", "inscription_id", "periode_id", "version",
                "fichier", "empreinte_sha256", "instantane", "cree_par_id", "cree_le",
            )
            if any(getattr(self, champ) != getattr(original, champ) for champ in immuables):
                raise ValidationError("Le contenu d'un document de résultats est immuable.")
            if original.revoque_le and (
                self.revoque_le != original.revoque_le or self.motif_revocation != original.motif_revocation
            ):
                raise ValidationError("La révocation d'un document ne peut pas être modifiée.")
            if self.revoque_le and not self.motif_revocation.strip():
                raise ValidationError("Un motif est obligatoire pour révoquer un document.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un document de résultats ne peut pas être supprimé.")
