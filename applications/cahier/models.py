import os
import uuid
from datetime import datetime, time as datetime_time

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from applications.academique.models import Classe
from applications.apprenants.models import Inscription
from applications.noyau.models import Appartenance, ModeleEtablissement
from applications.pedagogie.models import MatiereNiveau

from .stockage import EXTENSIONS_AUTORISEES, StockagePrive


stockage_prive = StockagePrive()


def chemin_piece_cahier(instance, nom_fichier):
    extension = os.path.splitext(nom_fichier)[1].lower()
    return f"etablissements/{instance.etablissement_id}/cahier/{uuid.uuid4().hex}{extension}"


class EntreeCahier(ModeleEtablissement):
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="entrees_cahier")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.PROTECT, related_name="entrees_cahier")
    enseignant = models.ForeignKey(
        Appartenance, on_delete=models.PROTECT, null=True, blank=True, related_name="entrees_cahier",
    )
    date = models.DateField("date de la séance")
    titre = models.CharField("titre", max_length=150)
    contenu = models.TextField("contenu")
    fichier = models.FileField(
        "document joint", upload_to=chemin_piece_cahier, blank=True, storage=stockage_prive,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
    )
    cree_le = models.DateTimeField("créée le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "séance du cahier de textes"
        verbose_name_plural = "séances du cahier de textes"
        ordering = ["-date", "-pk"]

    def __str__(self):
        return f"{self.titre} · {self.classe} · {self.date:%d/%m/%Y}"


class Devoir(ModeleEtablissement):
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="devoirs")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.PROTECT, related_name="devoirs")
    enseignant = models.ForeignKey(
        Appartenance, on_delete=models.PROTECT, null=True, blank=True, related_name="devoirs",
    )
    titre = models.CharField("titre", max_length=150)
    consigne = models.TextField("consigne")
    date_limite = models.DateField("date limite")
    heure_limite = models.TimeField("heure limite", default=datetime_time(23, 59))
    remise_numerique = models.BooleanField("autoriser une remise en ligne", default=True)
    accepter_remises_tardives = models.BooleanField("accepter les remises tardives", default=True)
    modifier_apres_echeance = models.BooleanField("autoriser les modifications après l'échéance", default=True)
    bareme = models.DecimalField("note maximale", max_digits=7, decimal_places=2, default=100)
    fichier = models.FileField(
        "document joint", upload_to=chemin_piece_cahier, blank=True, storage=stockage_prive,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
    )
    cree_le = models.DateTimeField("publié le", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "devoir"
        verbose_name_plural = "devoirs"
        ordering = ["date_limite", "-pk"]

    def __str__(self):
        return f"{self.titre} · {self.classe}"

    @property
    def echeance(self):
        return timezone.make_aware(
            datetime.combine(self.date_limite, self.heure_limite),
            timezone.get_current_timezone(),
        )


class Remise(ModeleEtablissement):
    devoir = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name="remises")
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="remises_devoirs")
    fichier = models.FileField(
        "travail remis", upload_to=chemin_piece_cahier, storage=stockage_prive,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
    )
    commentaire = models.CharField("commentaire", max_length=1000, blank=True)
    appreciation = models.CharField("appréciation", max_length=1000, blank=True)
    note = models.DecimalField("note", max_digits=7, decimal_places=2, null=True, blank=True)
    corrige_le = models.DateTimeField("corrigé le", null=True, blank=True)
    correcteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="remises_corrigees",
    )
    en_retard = models.BooleanField("remis en retard", default=False)
    remise_le = models.DateTimeField("remis le", default=timezone.now)

    class Meta:
        verbose_name = "remise de devoir"
        verbose_name_plural = "remises de devoirs"
        ordering = ["-remise_le", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["devoir", "inscription"], name="unique_remise_devoir_inscription"),
        ]

    def __str__(self):
        return f"{self.devoir} · {self.inscription.apprenant}"

    @property
    def statut(self):
        if self.note is not None:
            return "NOTE"
        return "EN_RETARD" if self.en_retard else "RENDU"


class PieceJointeDevoir(ModeleEtablissement):
    devoir = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name="pieces_jointes")
    fichier = models.FileField(
        "fichier", upload_to=chemin_piece_cahier, storage=stockage_prive,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
    )
    nom = models.CharField("nom du fichier", max_length=255)

    class Meta:
        verbose_name = "pièce jointe de devoir"
        verbose_name_plural = "pièces jointes de devoir"


class PieceJointeRemise(ModeleEtablissement):
    remise = models.ForeignKey(Remise, on_delete=models.CASCADE, related_name="pieces_jointes")
    fichier = models.FileField(
        "fichier", upload_to=chemin_piece_cahier, storage=stockage_prive,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
    )
    nom = models.CharField("nom du fichier", max_length=255)

    class Meta:
        verbose_name = "pièce jointe de remise"
        verbose_name_plural = "pièces jointes de remise"


class NotificationCahier(ModeleEtablissement):
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications_cahier",
    )
    titre = models.CharField("titre", max_length=150)
    texte = models.CharField("message", max_length=300, blank=True)
    url = models.CharField("lien", max_length=255)
    lue = models.BooleanField("lue", default=False)
    creee_le = models.DateTimeField("créée le", default=timezone.now)

    class Meta:
        verbose_name = "notification du cahier de textes"
        verbose_name_plural = "notifications du cahier de textes"
        ordering = ["-creee_le", "-pk"]

    def __str__(self):
        return self.titre
