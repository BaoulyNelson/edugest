"""Opérations financières enregistrées par établissement."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from applications.academique.models import AnneeAcademique, Niveau
from applications.apprenants.models import Apprenant, Inscription
from applications.noyau.models import ModeleEtablissement


class Paiement(ModeleEtablissement):
    class Mode(models.TextChoices):
        ESPECES = "ESPECES", "Espèces"
        VIREMENT = "VIREMENT", "Virement"
        CHEQUE = "CHEQUE", "Chèque"
        AUTRE = "AUTRE", "Autre"

    apprenant = models.ForeignKey(Apprenant, on_delete=models.PROTECT, related_name="paiements")
    montant = models.DecimalField("montant", max_digits=12, decimal_places=2)
    date_paiement = models.DateField("date du paiement", default=timezone.localdate)
    motif = models.CharField("motif", max_length=180)
    mode = models.CharField("mode de paiement", max_length=10, choices=Mode.choices, default=Mode.ESPECES)
    facture = models.ForeignKey(
        "Facture", on_delete=models.PROTECT, null=True, blank=True, related_name="paiements"
    )
    reference = models.CharField("référence", max_length=80, blank=True)
    numero_recu = models.CharField("numéro de reçu", max_length=30, unique=True, null=True, blank=True)
    recu_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    enregistre_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cree_le = models.DateTimeField("enregistré le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "paiement"
        verbose_name_plural = "paiements"
        ordering = ["-date_paiement", "-id"]
        constraints = [
            models.CheckConstraint(check=Q(montant__gt=0), name="paiement_montant_positif"),
        ]

    def __str__(self):
        return f"Paiement #{self.pk} — {self.apprenant}"


class Depense(ModeleEtablissement):
    class Categorie(models.TextChoices):
        SALAIRES = "SALAIRES", "Salaires"
        FOURNITURES = "FOURNITURES", "Fournitures"
        ENTRETIEN = "ENTRETIEN", "Entretien"
        ENERGIE = "ENERGIE", "Eau, électricité et internet"
        PERSONNEL = "PERSONNEL", "Personnel"
        TRANSPORT = "TRANSPORT", "Transport"
        IMPOTS = "IMPOTS", "Impôts et taxes"
        AUTRE = "AUTRE", "Autre"

    montant = models.DecimalField("montant", max_digits=12, decimal_places=2)
    date_depense = models.DateField("date de la dépense", default=timezone.localdate)
    categorie = models.CharField("catégorie", max_length=15, choices=Categorie.choices)
    motif = models.CharField("motif", max_length=180)
    enregistree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    cree_le = models.DateTimeField("enregistrée le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "dépense"
        verbose_name_plural = "dépenses"
        ordering = ["-date_depense", "-id"]
        constraints = [
            models.CheckConstraint(check=Q(montant__gt=0), name="depense_montant_positif"),
        ]

    def __str__(self):
        return f"Dépense #{self.pk} — {self.motif}"


class TypeFrais(ModeleEtablissement):
    nom = models.CharField("nom", max_length=80)
    actif = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "type de frais"
        verbose_name_plural = "types de frais"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "nom"], name="type_frais_nom_unique")
        ]

    def __str__(self):
        return self.nom


class GrilleFrais(ModeleEtablissement):
    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="grilles_frais")
    niveau = models.ForeignKey(Niveau, on_delete=models.PROTECT, related_name="grilles_frais")
    type_frais = models.ForeignKey(TypeFrais, on_delete=models.PROTECT, related_name="grilles")
    montant = models.DecimalField("montant", max_digits=12, decimal_places=2)
    nombre_echeances = models.PositiveSmallIntegerField("nombre d'échéances", default=1)
    premiere_echeance = models.DateField("date de la première échéance")

    class Meta:
        verbose_name = "grille de frais"
        verbose_name_plural = "grilles de frais"
        ordering = ["annee", "niveau", "type_frais"]
        constraints = [
            models.UniqueConstraint(fields=["annee", "niveau", "type_frais"], name="grille_frais_unique"),
            models.CheckConstraint(check=Q(montant__gt=0), name="grille_frais_montant_positif"),
            models.CheckConstraint(check=Q(nombre_echeances__gte=1, nombre_echeances__lte=12), name="grille_frais_echeances_valides"),
        ]

    def __str__(self):
        return f"{self.type_frais} · {self.niveau} · {self.annee}"


class Facture(ModeleEtablissement):
    class Statut(models.TextChoices):
        EMISE = "EMISE", "À payer"
        PARTIELLE = "PARTIELLE", "Partiellement payée"
        SOLDEE = "SOLDEE", "Soldée"
        ANNULEE = "ANNULEE", "Annulée"

    inscription = models.OneToOneField(Inscription, on_delete=models.PROTECT, related_name="facture")
    numero = models.CharField("numéro", max_length=30)
    total = models.DecimalField("total", max_digits=12, decimal_places=2, default=0)
    devise = models.CharField("devise", max_length=3, default="HTG")
    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.EMISE)
    date_emission = models.DateField("date d'émission", default=timezone.localdate)

    class Meta:
        verbose_name = "facture"
        verbose_name_plural = "factures"
        ordering = ["-date_emission", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "numero"], name="facture_numero_unique")
        ]

    def __str__(self):
        return self.numero


class LigneFacture(ModeleEtablissement):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name="lignes")
    libelle = models.CharField("libellé", max_length=120)
    montant = models.DecimalField("montant", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "ligne de facture"
        verbose_name_plural = "lignes de facture"
        ordering = ["pk"]


class Echeance(ModeleEtablissement):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name="echeances")
    ordre = models.PositiveSmallIntegerField("ordre")
    libelle = models.CharField("libellé", max_length=120)
    montant = models.DecimalField("montant", max_digits=12, decimal_places=2)
    date_limite = models.DateField("date limite")

    class Meta:
        verbose_name = "échéance"
        verbose_name_plural = "échéances"
        ordering = ["date_limite", "ordre", "pk"]


class AffectationPaiement(ModeleEtablissement):
    """Imputation détaillée d'un encaissement à une ou plusieurs échéances."""

    paiement = models.ForeignKey(Paiement, on_delete=models.PROTECT, related_name="affectations")
    echeance = models.ForeignKey(Echeance, on_delete=models.PROTECT, related_name="affectations")
    montant = models.DecimalField("montant affecté", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "affectation de paiement"
        verbose_name_plural = "affectations de paiement"
        constraints = [
            models.UniqueConstraint(fields=["paiement", "echeance"], name="paiement_echeance_unique"),
            models.CheckConstraint(check=models.Q(montant__gt=0), name="affectation_montant_positif"),
        ]


class Remboursement(ModeleEtablissement):
    """Remboursement tracé et lié à l'encaissement d'origine."""

    paiement = models.ForeignKey(Paiement, on_delete=models.PROTECT, related_name="remboursements")
    montant = models.DecimalField("montant remboursé", max_digits=12, decimal_places=2)
    motif = models.TextField("motif")
    effectue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    date_remboursement = models.DateTimeField("remboursé le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "remboursement"
        verbose_name_plural = "remboursements"
        ordering = ["-date_remboursement", "-pk"]
        constraints = [
            models.CheckConstraint(check=models.Q(montant__gt=0), name="remboursement_montant_positif")
        ]
