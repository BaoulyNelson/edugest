from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from applications.academique.models import AnneeAcademique, Niveau
from applications.academique.services import annee_active
from applications.interface.terminologie import profil_etablissement
from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Role
from applications.noyau import saas
from applications.apprenants.models import Inscription

from . import services
from .forms import (
    FormulaireAffectation, FormulaireDerogation, FormulaireInvitationEnseignant, FormulaireMatiere,
    FormulaireMatiereNiveau, FormulaireQuiz, FormulaireRessource,
)
from .models import (
    AffectationEnseignant, DerogationClasse, Matiere, MatiereNiveau,
    QuestionQuiz, Quiz, RessourcePedagogique,
)


PERMISSIONS_CONTENUS = (
    "pedagogie.gerer", "cahier.gerer", "cahier.gerer_tous",
    "cahier.consulter", "devoirs.remettre",
)


def _gestionnaire_contenus(request):
    return any(a_la_permission(request, code) for code in PERMISSIONS_CONTENUS[:3])


def _tout_contenu(request):
    return a_la_permission(request, "pedagogie.gerer") or a_la_permission(request, "cahier.gerer_tous")


def _paires_contenus(request):
    from applications.cahier.services import paires_accessibles

    return paires_accessibles(request.etablissement, request.appartenance, _tout_contenu(request))


def _inscriptions_accessibles(request):
    return Inscription.objects.filter(
        statut=Inscription.Statut.VALIDEE, classe__isnull=False,
    ).filter(
        Q(apprenant__utilisateur=request.user)
        | Q(apprenant__liens_responsables__responsable__utilisateur=request.user)
    ).distinct()


@permission_requise("pedagogie.gerer")
def matieres(request):
    formulaire = FormulaireMatiere(request.POST or None)
    libelle_cours = profil_etablissement(request.etablissement.type)["libelles"]["cours_singulier"]
    formulaire.fields["nom"].label = f"Nom : {libelle_cours}"
    formulaire.fields["nom"].help_text = (
        "Ajoutez le nom au référentiel sans choisir de niveau. "
        "L’association à un niveau et son barème se configurent séparément."
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.creer_matiere(request.etablissement, formulaire.cleaned_data["nom"])
        except ErreurMetier as erreur:
            formulaire.add_error("nom", str(erreur))
        else:
            messages.success(request, "Matière ajoutée.")
            return redirect("pedagogie:matieres")
    return render(request, "pedagogie/matieres.html", {
        "formulaire": formulaire, "matieres": Matiere.objects.all(), "niveaux": Niveau.objects.select_related("programme"),
    })


@permission_requise("pedagogie.gerer")
def niveau(request, pk):
    """Matières et barèmes d'un niveau : les classes du niveau en héritent sans configuration."""
    niveau_obj = get_object_or_404(Niveau, pk=pk)
    annee = AnneeAcademique.objects.filter(pk=request.GET.get("annee")).first() or annee_active(request.etablissement)
    if annee is None:
        messages.warning(request, "Créez et activez une année académique pour configurer les matières.")
        return redirect("academique:annees")
    formulaire = FormulaireMatiereNiveau(request.POST if request.POST.get("cible") == "matiere" else None)
    derogation = FormulaireDerogation(
        request.POST if request.POST.get("cible") == "derogation" else None, niveau=niveau_obj, annee=annee
    )
    if request.method == "POST":
        try:
            if request.POST.get("cible") == "matiere" and formulaire.is_valid():
                d = formulaire.cleaned_data
                services.definir_matiere_niveau(annee, niveau_obj, d["matiere"], d["bareme"], d["coefficient"], par=request.user)
                messages.success(request, "Barème enregistré pour le niveau.")
                return redirect(f"{request.path}?annee={annee.pk}")
            if request.POST.get("cible") == "derogation" and derogation.is_valid():
                d = derogation.cleaned_data
                services.definir_derogation(d["classe"], d["matiere_niveau"], d["bareme"], d["coefficient"], d["exclue"], par=request.user)
                messages.success(request, "Dérogation enregistrée.")
                return redirect(f"{request.path}?annee={annee.pk}")
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
    return render(request, "pedagogie/niveau.html", {
        "niveau": niveau_obj, "annee": annee, "annees": AnneeAcademique.objects.all(),
        "elements": MatiereNiveau.objects.filter(niveau=niveau_obj, annee=annee).select_related("matiere"),
        "derogations": DerogationClasse.objects.filter(matiere_niveau__niveau=niveau_obj, matiere_niveau__annee=annee)
        .select_related("classe", "matiere_niveau__matiere"),
        "formulaire": formulaire, "formulaire_derogation": derogation,
    })


@permission_requise("pedagogie.gerer")
def affectations(request):
    formulaire = FormulaireAffectation(request.POST or None, etablissement=request.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        d = formulaire.cleaned_data
        try:
            services.affecter_enseignant(d["enseignant"], d["matiere_niveau"], d["classe"], par=request.user)
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Affectation enregistrée.")
            return redirect("pedagogie:affectations")
    annee = annee_active(request.etablissement)
    liste = AffectationEnseignant.objects.select_related(
        "appartenance__utilisateur", "matiere_niveau__matiere", "matiere_niveau__niveau", "classe"
    )
    if annee:
        liste = liste.filter(matiere_niveau__annee=annee)
    return render(request, "pedagogie/affectations.html", {
        "formulaire": formulaire, "affectations": liste, "annee": annee,
        "peut_inviter_enseignant": a_la_permission(request, "pedagogie.gerer"),
    })


@permission_requise("pedagogie.gerer")
@require_POST
def inviter_enseignant(request):
    formulaire = FormulaireInvitationEnseignant(request.POST)
    if not formulaire.is_valid():
        messages.error(request, "Saisissez une adresse e-mail valide pour l’enseignant.")
        return redirect("pedagogie:affectations")
    email = formulaire.cleaned_data["email"]
    role = Role.objects.filter(nom="Enseignant").first()
    if role is None:
        messages.error(request, "Le rôle Enseignant n’est pas configuré dans cet établissement.")
        return redirect("pedagogie:affectations")
    try:
        saas.inviter(
            request.etablissement, email, role, request.user,
            request.build_absolute_uri("/").rstrip("/"),
        )
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        if saas.courriel_en_mode_console():
            messages.warning(
                request,
                f"L’invitation pour {email} a été créée, mais aucun e-mail n’a été livré : "
                "le message est affiché dans le terminal du serveur.",
            )
        else:
            messages.success(request, f"Invitation envoyée à {email}.")
    return redirect("pedagogie:affectations")


@permission_requise(*PERMISSIONS_CONTENUS)
def ressources(request):
        gestionnaire = _gestionnaire_contenus(request)
        tout = _tout_contenu(request)
        paires = _paires_contenus(request) if gestionnaire else set()
        formulaire_ressource = FormulaireRessource(paires=paires)
        formulaire_quiz = FormulaireQuiz(paires=paires)

        if request.method == "POST":
            cible = request.POST.get("cible")
            if not gestionnaire:
                raise PermissionDenied
            if cible == "ressource":
                formulaire_ressource = FormulaireRessource(request.POST, request.FILES, paires=paires)
                if formulaire_ressource.is_valid():
                    donnees = formulaire_ressource.cleaned_data
                    try:
                        services.creer_ressource(
                            request.etablissement, request.appartenance, donnees["classe"],
                            donnees["matiere_niveau"], donnees["titre"], donnees["description"],
                            donnees["fichier"], tout=tout, par=request.user,
                        )
                    except ErreurMetier as erreur:
                        formulaire_ressource.add_error(None, str(erreur))
                    else:
                        messages.success(request, "Ressource pédagogique publiée.")
                        return redirect("pedagogie:ressources")
            elif cible == "quiz":
                formulaire_quiz = FormulaireQuiz(request.POST, paires=paires)
                if formulaire_quiz.is_valid():
                    donnees = formulaire_quiz.cleaned_data
                    try:
                        services.creer_quiz(
                            request.etablissement, request.appartenance, donnees["classe"],
                            donnees["matiere_niveau"], donnees["titre"], donnees["description"],
                            donnees["questions"], donnees["date_limite"], donnees["nombre_tentatives_max"],
                            tout=tout, par=request.user,
                        )
                    except ErreurMetier as erreur:
                        formulaire_quiz.add_error(None, str(erreur))
                    else:
                        messages.success(request, "Quiz publié.")
                        return redirect("pedagogie:ressources")
            else:
                messages.error(request, "Type de contenu inconnu.")

        if gestionnaire:
            ressources_liste = RessourcePedagogique.objects.select_related(
                "classe", "matiere_niveau__matiere", "enseignant__utilisateur"
            )
            quiz_liste = Quiz.objects.select_related("classe", "matiere_niveau__matiere", "enseignant__utilisateur")
            if not tout:
                ressources_liste = ressources_liste.filter(enseignant=request.appartenance)
                quiz_liste = quiz_liste.filter(enseignant=request.appartenance)
        else:
            classes_ids = _inscriptions_accessibles(request).values_list("classe_id", flat=True)
            ressources_liste = RessourcePedagogique.objects.filter(classe_id__in=classes_ids).select_related(
                "classe", "matiere_niveau__matiere", "enseignant__utilisateur"
            )
            quiz_liste = Quiz.objects.filter(classe_id__in=classes_ids, ouvert=True).select_related(
                "classe", "matiere_niveau__matiere", "enseignant__utilisateur"
            )
        return render(request, "pedagogie/ressources.html", {
            "ressources": ressources_liste[:100], "quiz": quiz_liste[:100],
            "gestionnaire": gestionnaire,
            "formulaire_ressource": formulaire_ressource, "formulaire_quiz": formulaire_quiz,
        })


@permission_requise(*PERMISSIONS_CONTENUS)
def telecharger_ressource(request, pk):
        ressource = get_object_or_404(RessourcePedagogique, pk=pk)
        if _gestionnaire_contenus(request):
            if not _tout_contenu(request) and ressource.enseignant_id != getattr(request.appartenance, "pk", None):
                raise PermissionDenied
        elif not _inscriptions_accessibles(request).filter(classe_id=ressource.classe_id).exists():
            raise PermissionDenied
        fichier = ressource.fichier.storage.open(ressource.fichier.name, "rb")
        nom = ressource.titre.replace('"', "").replace("\r", "").replace("\n", "")[:120]
        return FileResponse(fichier, as_attachment=True, filename=nom)


@permission_requise(*PERMISSIONS_CONTENUS)
def quiz_detail(request, pk):
        quiz = get_object_or_404(
            Quiz.objects.select_related("classe", "matiere_niveau__matiere", "enseignant"), pk=pk
        )
        gestionnaire = _gestionnaire_contenus(request)
        tout = _tout_contenu(request)
        if gestionnaire:
            if not tout and quiz.enseignant_id != getattr(request.appartenance, "pk", None):
                raise PermissionDenied
            inscription = None
        else:
            inscriptions = _inscriptions_accessibles(request).filter(classe=quiz.classe)
            if not inscriptions.exists():
                raise PermissionDenied
            inscription = services.inscription_apprenant_pour_quiz(quiz, request.user)

        questions = list(QuestionQuiz.objects.filter(quiz=quiz).prefetch_related("choix"))
        tentative = None
        if request.GET.get("tentative") and inscription is not None:
            tentative = get_object_or_404(
                quiz.tentatives.filter(inscription=inscription),
                pk=request.GET["tentative"],
            )

        if request.method == "POST":
            if gestionnaire or inscription is None or not a_la_permission(request, "devoirs.remettre"):
                raise PermissionDenied("Seul l'apprenant inscrit peut répondre à ce quiz.")
            try:
                tentative = services.soumettre_quiz(
                    quiz, inscription,
                    {str(question.pk): request.POST.get(f"question_{question.pk}", "") for question in questions},
                    request.user,
                )
            except ErreurMetier as erreur:
                messages.error(request, str(erreur))
            else:
                return redirect(f"{request.path}?tentative={tentative.pk}")

        options = [
            {"question": question, "choix": list(question.choix.values("pk", "texte"))}
            for question in questions
        ]
        nombre_tentatives = (
            quiz.tentatives.filter(inscription=inscription).count() if inscription is not None else 0
        )
        return render(request, "pedagogie/quiz_detail.html", {
            "quiz": quiz, "questions": options, "tentative": tentative,
            "peut_repondre": bool(
                inscription and quiz.ouvert and a_la_permission(request, "devoirs.remettre")
                and (not quiz.date_limite or quiz.date_limite >= timezone.now())
                and nombre_tentatives < quiz.nombre_tentatives_max
            ),
            "nombre_tentatives": nombre_tentatives,
        })
