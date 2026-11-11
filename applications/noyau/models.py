"""Modèles du noyau : établissements, utilisateurs, rôles, audit."""
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .contexte import obtenir_etablissement_courant
from .permissions import CATALOGUE


class TypeEtablissement(models.TextChoices):
    SCOLAIRE = "SCOLAIRE", "École classique"
    UNIVERSITAIRE = "UNIVERSITAIRE", "Université"
    PROFESSIONNEL = "PROFESSIONNEL", "École professionnelle"


class ModeleValide(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Etablissement(ModeleValide):
    """Un établissement = un espace de travail (tenant) isolé des autres."""

    LANGUES = (
        ("fr", "Français"),
        ("en", "English"),
        ("es", "Español"),
        ("ht", "Kreyòl ayisyen"),
    )

    nom = models.CharField("nom", max_length=200)
    nom_court = models.CharField("nom court / sigle", max_length=50, blank=True)
    slogan = models.CharField("slogan", max_length=255, blank=True)
    devise = models.CharField("devise (code ISO)", max_length=3, default="HTG")
    langue = models.CharField("langue de l'interface", max_length=5, choices=LANGUES, default="fr")
    fuseau_horaire = models.CharField("fuseau horaire", max_length=64, default="America/Port-au-Prince")
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    email = models.EmailField("adresse e-mail", blank=True)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    site_web = models.URLField("site web", blank=True)
    slug = models.SlugField("identifiant", max_length=80, unique=True, editable=False)
    type = models.CharField("type", max_length=20, choices=TypeEtablissement.choices)
    logo = models.ImageField("logo", upload_to="logos/", blank=True)
    actif = models.BooleanField("actif", default=True)
    cree_le = models.DateTimeField("créé le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "établissement"
        verbose_name_plural = "établissements"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nom)[:60] or "etablissement"
            candidat, numero = base, 1
            while Etablissement.objects.filter(slug=candidat).exists():
                numero += 1
                candidat = f"{base}-{numero}"
            self.slug = candidat
        super().save(*args, **kwargs)

    @property
    def est_universitaire(self):
        return self.type == TypeEtablissement.UNIVERSITAIRE

    @property
    def est_professionnel(self):
        return self.type == TypeEtablissement.PROFESSIONNEL


class ConfigurationPlateforme(ModeleValide):
    """Identité globale affichée sur les pages publiques et les interfaces de l'ERP."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    nom = models.CharField("nom de la plateforme", max_length=100, default="EduGest")
    nom_court = models.CharField("nom court", max_length=50, blank=True)
    slogan = models.CharField("slogan", max_length=255, blank=True)
    logo = models.ImageField("logo", upload_to="plateforme/", blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    email = models.EmailField("adresse e-mail", blank=True)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    site_web = models.URLField("site web", blank=True)
    linkedin_url = models.URLField("page LinkedIn", blank=True)
    facebook_url = models.URLField("page Facebook", blank=True)
    instagram_url = models.URLField("compte Instagram", blank=True)
    pied_de_page = models.CharField(
        "texte du pied de page", max_length=500, blank=True,
        help_text="Texte de présentation ou mentions de marque affichés dans le pied de page public.",
    )
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "configuration de la plateforme"
        verbose_name_plural = "configuration de la plateforme"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La configuration principale de la plateforme ne peut pas être supprimée.")

    def __str__(self):
        return self.nom


class GestionnaireEtablissement(models.Manager):
    """Filtre automatiquement sur l'établissement courant (isolation côté serveur)."""

    def get_queryset(self):
        requete = super().get_queryset()
        identifiant = obtenir_etablissement_courant()
        if identifiant is not None:
            requete = requete.filter(etablissement_id=identifiant)
        return requete


class ModeleEtablissement(ModeleValide):
    """Base commune des entités rattachées à un établissement (seule propriété réellement partagée)."""

    etablissement = models.ForeignKey(
        Etablissement, on_delete=models.PROTECT, related_name="+", verbose_name="établissement"
    )

    objects = GestionnaireEtablissement()
    sans_filtre = models.Manager()

    class Meta:
        abstract = True

    def clean(self):
        if self.etablissement_id is None:
            return
        erreurs = {}
        for field in self._meta.concrete_fields:
            if not isinstance(field, models.ForeignKey) or field.name == "etablissement":
                continue
            related_model = field.remote_field.model
            if not any(candidate.name == "etablissement" for candidate in related_model._meta.fields):
                continue
            relation_id = getattr(self, field.attname)
            if relation_id is None:
                continue
            etablissement_id = related_model._base_manager.filter(pk=relation_id).values_list(
                "etablissement_id", flat=True
            ).first()
            if etablissement_id is not None and etablissement_id != self.etablissement_id:
                erreurs[field.name] = "Cette relation doit appartenir au même établissement."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        courant = obtenir_etablissement_courant()
        if self.etablissement_id is None and courant:
            self.etablissement_id = courant
        elif courant and self.etablissement_id != courant:
            raise ValidationError("Enregistrement refusé : l'objet appartient à un autre établissement.")
        super().save(*args, **kwargs)


class Utilisateur(AbstractUser):
    email = models.EmailField("adresse e-mail", unique=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    email_verifie = models.BooleanField("adresse e-mail vérifiée", default=False)

    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def nom_affiche(self):
        return self.get_full_name() or self.username


class Role(ModeleEtablissement):
    nom = models.CharField("nom", max_length=100)
    codes = models.JSONField("permissions", default=list, blank=True)

    class Meta:
        verbose_name = "rôle"
        verbose_name_plural = "rôles"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "nom"], name="unique_role_par_etablissement")
        ]

    def __str__(self):
        return self.nom

    def clean(self):
        inconnus = [code for code in self.codes if code not in CATALOGUE]
        if inconnus:
            raise ValidationError(f"Permissions inconnues : {', '.join(inconnus)}")


class Appartenance(ModeleEtablissement):
    """Rattachement d'un utilisateur à un établissement avec un rôle."""

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.CASCADE, related_name="appartenances", verbose_name="utilisateur"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="appartenances", verbose_name="rôle")
    actif = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "appartenance"
        verbose_name_plural = "appartenances"
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "etablissement"], name="unique_appartenance")
        ]

    def __str__(self):
        return f"{self.utilisateur.nom_affiche} ({self.role})"


class VocabulaireInstitutionnel(ModeleEtablissement):
    cle = models.CharField("clé", max_length=50)
    libelle_singulier = models.CharField("libellé (singulier)", max_length=100)
    libelle_pluriel = models.CharField("libellé (pluriel)", max_length=100)

    class Meta:
        verbose_name = "vocabulaire institutionnel"
        verbose_name_plural = "vocabulaire institutionnel"
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "cle"], name="unique_vocabulaire")
        ]

    def __str__(self):
        return f"{self.cle} → {self.libelle_singulier}"


class ParametresEtablissement(ModeleValide):
    etablissement = models.OneToOneField(
        Etablissement, on_delete=models.CASCADE, related_name="parametres", verbose_name="établissement"
    )
    seuil_reussite_pct = models.DecimalField(
        "seuil de réussite (% du barème)", max_digits=5, decimal_places=2, default=50
    )
    echelle_moyenne = models.PositiveIntegerField("échelle d'affichage des moyennes", default=20)
    classement_autorise = models.BooleanField("classement autorisé", default=False)
    nombre_periodes_par_annee = models.PositiveSmallIntegerField(
        "périodes par année académique", default=3
    )
    retention_annees = models.PositiveSmallIntegerField(
        "conservation des dossiers après la dernière inscription (années)", default=5
    )

    class Meta:
        verbose_name = "paramètres de l'établissement"
        verbose_name_plural = "paramètres des établissements"
        constraints = [
            models.CheckConstraint(
                check=models.Q(seuil_reussite_pct__gt=0, seuil_reussite_pct__lte=100),
                name="seuil_reussite_valide",
            ),
            models.CheckConstraint(
                check=models.Q(nombre_periodes_par_annee__gte=1, nombre_periodes_par_annee__lte=12),
                name="nombre_periodes_par_annee_valide",
            ),
            models.CheckConstraint(
                check=models.Q(retention_annees__gte=1, retention_annees__lte=20),
                name="retention_annees_valide",
            ),
        ]

    def __str__(self):
        return f"Paramètres de {self.etablissement}"


class SequenceNumerotation(ModeleEtablissement):
    cle = models.CharField("clé", max_length=50)
    derniere_valeur = models.PositiveIntegerField("dernière valeur", default=0)

    class Meta:
        verbose_name = "séquence de numérotation"
        verbose_name_plural = "séquences de numérotation"
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "cle"], name="unique_sequence")
        ]


class JournalAudit(ModeleValide):
    """Historique des opérations sensibles. Une ligne n'est jamais modifiée ni supprimée."""

    etablissement = models.ForeignKey(
        Etablissement, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField("action", max_length=100)
    objet_type = models.CharField("type d'objet", max_length=100, blank=True)
    objet_id = models.CharField("identifiant de l'objet", max_length=50, blank=True)
    avant = models.JSONField("avant", null=True, blank=True, encoder=DjangoJSONEncoder)
    apres = models.JSONField("après", null=True, blank=True, encoder=DjangoJSONEncoder)
    motif = models.TextField("motif", blank=True)
    date = models.DateTimeField("date", auto_now_add=True)

    class Meta:
        verbose_name = "ligne du journal d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Le journal d'audit ne peut pas être modifié.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le journal d'audit ne peut pas être supprimé.")


class Plan(ModeleValide):
    """Formule d'abonnement : limites d'usage d'un établissement."""

    code = models.CharField("code", max_length=20, unique=True)
    nom = models.CharField("nom", max_length=100)
    limite_apprenants = models.PositiveIntegerField("limite d'apprenants", null=True, blank=True, help_text="Vide = illimité")
    limite_membres = models.PositiveIntegerField("limite de membres du personnel", null=True, blank=True, help_text="Vide = illimité")
    prix_mensuel = models.DecimalField("prix mensuel (USD)", max_digits=8, decimal_places=2, default=0)

    class Meta:
        verbose_name = "plan"
        verbose_name_plural = "plans"
        ordering = ["prix_mensuel"]

    def __str__(self):
        return self.nom


class Abonnement(ModeleValide):
    class Statut(models.TextChoices):
        ESSAI = "ESSAI", "Période d'essai"
        ACTIF = "ACTIF", "Actif"
        SUSPENDU = "SUSPENDU", "Suspendu"
        RESILIE = "RESILIE", "Résilié"

    etablissement = models.OneToOneField(Etablissement, on_delete=models.CASCADE, related_name="abonnement")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="abonnements")
    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.ESSAI)
    date_debut = models.DateField("début", default=timezone.localdate)
    date_fin_essai = models.DateField("fin de l'essai", null=True, blank=True)

    def clean(self):
        if self.date_debut and self.date_fin_essai and self.date_fin_essai < self.date_debut:
            raise ValidationError({
                "date_fin_essai": "La fin de l'essai ne peut pas précéder le début de l'abonnement."
            })

    class Meta:
        verbose_name = "abonnement"
        verbose_name_plural = "abonnements"

    def __str__(self):
        return f"{self.etablissement} - {self.plan}"


class EvenementPaiement(ModeleValide):
    class Type(models.TextChoices):
        PAIEMENT_REUSSI = "PAIEMENT_REUSSI", "Paiement réussi"
        PAIEMENT_ECHOUE = "PAIEMENT_ECHOUE", "Paiement échoué"
        REMBOURSEMENT = "REMBOURSEMENT", "Remboursement"
        ABONNEMENT_MODIFIE = "ABONNEMENT_MODIFIE", "Abonnement modifié"

    etablissement = models.ForeignKey(
        Etablissement, on_delete=models.PROTECT, related_name="evenements_paiement"
    )
    abonnement = models.ForeignKey(
        Abonnement, on_delete=models.PROTECT, related_name="evenements_paiement"
    )
    fournisseur = models.CharField(max_length=40)
    identifiant_externe = models.CharField(max_length=150)
    type_evenement = models.CharField(max_length=24, choices=Type.choices)
    donnees = models.JSONField(default=dict, encoder=DjangoJSONEncoder, blank=True)
    recu_le = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        if self.etablissement_id and self.abonnement_id:
            etablissement_abonnement = Abonnement._base_manager.filter(
                pk=self.abonnement_id
            ).values_list("etablissement_id", flat=True).first()
            if etablissement_abonnement is not None and etablissement_abonnement != self.etablissement_id:
                raise ValidationError({
                    "abonnement": "L'abonnement doit appartenir au même établissement."
                })

    class Meta:
        verbose_name = "événement de paiement"
        verbose_name_plural = "événements de paiement"
        ordering = ["-recu_le", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["etablissement", "fournisseur", "identifiant_externe"],
                name="evenement_paiement_idempotent",
            )
        ]


class UsageAbonnement(ModeleValide):
    etablissement = models.ForeignKey(
        Etablissement, on_delete=models.PROTECT, related_name="historique_usage"
    )
    date = models.DateField(default=timezone.localdate)
    nombre_apprenants = models.PositiveIntegerField()
    nombre_membres = models.PositiveIntegerField()
    invitations_en_attente = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "mesure d'utilisation d'abonnement"
        verbose_name_plural = "historique d'utilisation des abonnements"
        ordering = ["-date", "etablissement__nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "date"], name="usage_abonnement_jour_unique")
        ]


class Invitation(ModeleEtablissement):
    """Invitation envoyée par un administrateur : la personne crée elle-même son compte."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REVOQUEE = "REVOQUEE", "Révoquée"

    email = models.EmailField("adresse e-mail")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="invitations", verbose_name="rôle")
    apprenant = models.ForeignKey(
        "apprenants.Apprenant", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitations", verbose_name="dossier apprenant",
    )
    responsable = models.ForeignKey(
        "apprenants.ResponsableLegal", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitations", verbose_name="dossier du responsable",
    )
    jeton = models.CharField("jeton", max_length=64, unique=True, editable=False)
    statut = models.CharField("statut", max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    invitee_par = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, related_name="+")
    date_creation = models.DateTimeField("envoyée le", default=timezone.now)
    date_expiration = models.DateTimeField("expire le")

    class Meta:
        verbose_name = "invitation"
        verbose_name_plural = "invitations"
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.email} → {self.etablissement}"

    @property
    def est_valide(self):
        return self.statut == self.Statut.EN_ATTENTE and self.date_expiration > timezone.now()
