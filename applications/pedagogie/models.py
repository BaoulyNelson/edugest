"""Matières, barèmes par niveau et année, dérogations de classe, affectations des enseignants."""
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from applications.academique.models import AnneeAcademique, Classe, Niveau
from applications.apprenants.models import Inscription
from applications.cahier.stockage import EXTENSIONS_AUTORISEES, StockagePrive
from applications.noyau.models import Appartenance, ModeleEtablissement

stockage_ressources = StockagePrive()


def chemin_ressource(instance, nom_fichier):
    extension = os.path.splitext(nom_fichier)[1].lower()
    return f"etablissements/{instance.etablissement_id}/pedagogie/{uuid.uuid4().hex}{extension}"


class Matiere(ModeleEtablissement):
    """Référentiel de l'établissement : sans barème, qui dépend du niveau (voir MatiereNiveau)."""

    nom = models.CharField("nom", max_length=150)
    code = models.CharField("code", max_length=20, editable=False)

    class Meta:
        verbose_name = "matière"
        verbose_name_plural = "matières"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "nom"], name="unique_matiere"),
            models.UniqueConstraint(fields=["etablissement", "code"], name="unique_code_matiere"),
        ]

    def __str__(self):
        return self.nom


class MatiereNiveau(ModeleEtablissement):
    """Matière enseignée dans un niveau pour une année, avec son barème et son coefficient."""

    annee = models.ForeignKey(AnneeAcademique, on_delete=models.PROTECT, related_name="matieres_niveaux")
    niveau = models.ForeignKey(Niveau, on_delete=models.PROTECT, related_name="matieres_niveaux")
    matiere = models.ForeignKey(Matiere, on_delete=models.PROTECT, related_name="matieres_niveaux")
    bareme = models.DecimalField("barème", max_digits=7, decimal_places=2)
    coefficient = models.DecimalField("coefficient", max_digits=5, decimal_places=2, default=1)

    class Meta:
        verbose_name = "matière d'un niveau"
        verbose_name_plural = "matières des niveaux"
        ordering = ["niveau__ordre", "matiere__nom"]
        constraints = [
            models.UniqueConstraint(fields=["annee", "niveau", "matiere"], name="unique_matiere_niveau"),
            models.CheckConstraint(check=models.Q(bareme__gt=0), name="bareme_positif"),
            models.CheckConstraint(check=models.Q(coefficient__gt=0), name="coefficient_positif"),
        ]

    def __str__(self):
        return f"{self.matiere} - {self.niveau} ({self.bareme})"

    def clean(self):
        super().clean()
        for objet, libelle in (
            (self.annee, "L'année"),
            (self.niveau, "Le niveau"),
            (self.matiere, "La matière"),
        ):
            if objet.etablissement_id != self.etablissement_id:
                raise ValidationError(f"{libelle} et la matière de niveau doivent appartenir au même établissement.")


class DerogationClasse(ModeleEtablissement):
    """Exception explicite à la configuration du niveau (créée uniquement si nécessaire)."""

    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="derogations")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.CASCADE, related_name="derogations")
    bareme = models.DecimalField("barème dérogatoire", max_digits=7, decimal_places=2, null=True, blank=True)
    coefficient = models.DecimalField("coefficient dérogatoire", max_digits=5, decimal_places=2, null=True, blank=True)
    exclue = models.BooleanField("matière non enseignée dans cette classe", default=False)

    class Meta:
        verbose_name = "dérogation de classe"
        verbose_name_plural = "dérogations de classe"
        constraints = [models.UniqueConstraint(fields=["classe", "matiere_niveau"], name="unique_derogation")]


class AffectationEnseignant(ModeleEtablissement):
    appartenance = models.ForeignKey(Appartenance, on_delete=models.PROTECT, related_name="affectations")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.PROTECT, related_name="affectations")
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, null=True, blank=True, related_name="affectations")

    class Meta:
        verbose_name = "affectation d'enseignant"
        verbose_name_plural = "affectations d'enseignants"
        ordering = ["matiere_niveau__niveau__ordre", "matiere_niveau__matiere__nom"]

    def __str__(self):
        cible = self.classe or self.matiere_niveau.niveau
        return f"{self.matiere_niveau.matiere} - {cible} ({self.appartenance.utilisateur.nom_affiche})"

    def clean(self):
        super().clean()
        if self.appartenance_id and self.appartenance.etablissement_id != self.etablissement_id:
            raise ValidationError("L'appartenance et l'affectation doivent appartenir au même établissement.")
        if self.matiere_niveau_id and self.matiere_niveau.etablissement_id != self.etablissement_id:
            raise ValidationError("La matière et l'affectation doivent appartenir au même établissement.")
        if self.classe_id and self.classe.etablissement_id != self.etablissement_id:
            raise ValidationError("La classe et l'affectation doivent appartenir au même établissement.")
        if self.classe_id and self.classe.niveau_id != self.matiere_niveau.niveau_id:
            raise ValidationError("La classe n'appartient pas au niveau de la matière.")
        if self.classe_id and self.classe.annee_id != self.matiere_niveau.annee_id:
            raise ValidationError("La classe n'appartient pas à l'année de la matière.")
        if self.appartenance_id and self.matiere_niveau_id:
            affectations = AffectationEnseignant.sans_filtre.filter(
                appartenance_id=self.appartenance_id,
                matiere_niveau_id=self.matiere_niveau_id,
                classe_id=self.classe_id,
            )
            if self.pk:
                affectations = affectations.exclude(pk=self.pk)
            if affectations.exists():
                raise ValidationError("Cette affectation existe déjà.")


class RessourcePedagogique(ModeleEtablissement):
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="ressources")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.PROTECT, related_name="ressources")
    enseignant = models.ForeignKey(Appartenance, on_delete=models.PROTECT, related_name="ressources")
    titre = models.CharField("titre", max_length=150)
    description = models.TextField("description", blank=True)
    fichier = models.FileField(
        "fichier", upload_to=chemin_ressource, storage=stockage_ressources,
        validators=[FileExtensionValidator(allowed_extensions=EXTENSIONS_AUTORISEES)],
    )
    cree_le = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "ressource pédagogique"
        verbose_name_plural = "ressources pédagogiques"
        ordering = ["-cree_le", "-pk"]

    def clean(self):
        super().clean()
        if self.classe_id and self.matiere_niveau_id and self.classe.niveau_id != self.matiere_niveau.niveau_id:
            raise ValidationError("La matière n'appartient pas au niveau de la classe.")


class Quiz(ModeleEtablissement):
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="quiz")
    matiere_niveau = models.ForeignKey(MatiereNiveau, on_delete=models.PROTECT, related_name="quiz")
    enseignant = models.ForeignKey(Appartenance, on_delete=models.PROTECT, related_name="quiz")
    titre = models.CharField("titre", max_length=150)
    description = models.TextField("consignes", blank=True)
    date_limite = models.DateTimeField("date limite", null=True, blank=True)
    nombre_tentatives_max = models.PositiveSmallIntegerField(default=1)
    ouvert = models.BooleanField(default=True)
    cree_le = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "quiz"
        verbose_name_plural = "quiz"
        ordering = ["date_limite", "-cree_le"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(nombre_tentatives_max__gte=1, nombre_tentatives_max__lte=10),
                name="quiz_tentatives_valides",
            )
        ]

    def clean(self):
        super().clean()
        if self.classe_id and self.matiere_niveau_id and self.classe.niveau_id != self.matiere_niveau.niveau_id:
            raise ValidationError("La matière n'appartient pas au niveau de la classe.")


class QuestionQuiz(ModeleEtablissement):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    texte = models.TextField("question")
    ordre = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = "question de quiz"
        verbose_name_plural = "questions de quiz"
        ordering = ["ordre", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["quiz", "ordre"], name="quiz_question_ordre_unique")
        ]


class ChoixQuestion(ModeleEtablissement):
    question = models.ForeignKey(QuestionQuiz, on_delete=models.CASCADE, related_name="choix")
    texte = models.CharField("choix", max_length=300)
    correct = models.BooleanField(default=False)
    ordre = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = "choix de réponse"
        verbose_name_plural = "choix de réponse"
        ordering = ["ordre", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["question", "ordre"], name="quiz_choix_ordre_unique")
        ]


class TentativeQuiz(ModeleEtablissement):
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="tentatives")
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="tentatives_quiz")
    score = models.PositiveSmallIntegerField(default=0)
    soumise_le = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "tentative de quiz"
        verbose_name_plural = "tentatives de quiz"
        ordering = ["-soumise_le", "-pk"]


class ReponseQuiz(ModeleEtablissement):
    tentative = models.ForeignKey(TentativeQuiz, on_delete=models.CASCADE, related_name="reponses")
    question = models.ForeignKey(QuestionQuiz, on_delete=models.PROTECT, related_name="reponses")
    choix = models.ForeignKey(ChoixQuestion, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "réponse de quiz"
        verbose_name_plural = "réponses de quiz"
        constraints = [
            models.UniqueConstraint(fields=["tentative", "question"], name="quiz_reponse_unique")
        ]
