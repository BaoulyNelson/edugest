"""Services métier de la pédagogie : barèmes hérités, dérogations, affectations."""
from decimal import Decimal

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance
from applications.noyau.services import enregistrer_audit, servir_numero, verifier_permission

from .models import (
    AffectationEnseignant, ChoixQuestion, DerogationClasse, Matiere,
    MatiereNiveau, QuestionQuiz, Quiz, ReponseQuiz, RessourcePedagogique,
    TentativeQuiz,
)


def creer_matiere(etablissement, nom):
    nom = nom.strip()
    if Matiere.sans_filtre.filter(etablissement=etablissement, nom__iexact=nom).exists():
        raise ErreurMetier(f"La matière « {nom} » existe déjà.")
    code = f"MAT-{servir_numero(etablissement, 'matiere'):03d}"
    return Matiere.sans_filtre.create(etablissement=etablissement, nom=nom, code=code)


@transaction.atomic
def definir_matiere_niveau(annee, niveau, matiere, bareme, coefficient=1, par=None):
    """Définit (ou met à jour) le barème d'une matière dans un niveau pour une année."""
    bareme = Decimal(bareme)
    coefficient = Decimal(coefficient)
    if bareme <= 0 or coefficient <= 0:
        raise ErreurMetier("Le barème et le coefficient doivent être strictement positifs.")
    if not (annee.etablissement_id == niveau.etablissement_id == matiere.etablissement_id):
        raise ErreurMetier("Année, niveau et matière doivent appartenir au même établissement.")
    existant = MatiereNiveau.sans_filtre.filter(annee=annee, niveau=niveau, matiere=matiere).first()
    if existant is not None and existant.bareme != bareme:
        Configuration = apps.get_model("evaluations", "ConfigurationEvaluation")
        if Configuration.sans_filtre.filter(
            affectation__matiere_niveau=existant, statut__in=("VALIDEE", "VERROUILLEE")
        ).exists():
            raise ErreurMetier(
                "Le barème ne peut plus être modifié : des évaluations validées utilisent déjà ce barème."
            )
    if existant is None:
        resultat = MatiereNiveau.sans_filtre.create(
            etablissement=annee.etablissement, annee=annee, niveau=niveau, matiere=matiere,
            bareme=bareme, coefficient=coefficient,
        )
        enregistrer_audit(annee.etablissement, par, "bareme.creation", resultat, apres={"bareme": bareme})
        return resultat
    avant = {"bareme": existant.bareme, "coefficient": existant.coefficient}
    existant.bareme, existant.coefficient = bareme, coefficient
    existant.save(update_fields=["bareme", "coefficient"])
    enregistrer_audit(annee.etablissement, par, "bareme.modification", existant, avant=avant,
                      apres={"bareme": bareme, "coefficient": coefficient})
    return existant


def _derogation(matiere_niveau, classe):
    if classe is None:
        return None
    return DerogationClasse.sans_filtre.filter(classe=classe, matiere_niveau=matiere_niveau).first()


def bareme_applique(matiere_niveau, classe=None):
    """Barème de la classe : dérogation éventuelle, sinon barème hérité du niveau."""
    derogation = _derogation(matiere_niveau, classe)
    if derogation is not None and derogation.bareme is not None:
        return derogation.bareme
    return matiere_niveau.bareme


def coefficient_applique(matiere_niveau, classe=None):
    derogation = _derogation(matiere_niveau, classe)
    if derogation is not None and derogation.coefficient is not None:
        return derogation.coefficient
    return matiere_niveau.coefficient


def matiere_enseignee(matiere_niveau, classe=None):
    derogation = _derogation(matiere_niveau, classe)
    return not (derogation is not None and derogation.exclue)


def matieres_de_classe(classe):
    """Matières héritées du niveau, sans configuration par classe (sauf dérogation d'exclusion)."""
    exclues = DerogationClasse.sans_filtre.filter(classe=classe, exclue=True).values_list("matiere_niveau_id", flat=True)
    return MatiereNiveau.sans_filtre.filter(niveau=classe.niveau, annee=classe.annee).exclude(pk__in=list(exclues))


@transaction.atomic
def definir_derogation(classe, matiere_niveau, bareme=None, coefficient=None, exclue=False, par=None):
    if classe.niveau_id != matiere_niveau.niveau_id or classe.annee_id != matiere_niveau.annee_id:
        raise ErreurMetier("La classe et la matière ne correspondent pas au même niveau et à la même année.")
    derogation, _ = DerogationClasse.sans_filtre.update_or_create(
        classe=classe, matiere_niveau=matiere_niveau,
        defaults={"etablissement": classe.etablissement, "bareme": bareme, "coefficient": coefficient, "exclue": exclue},
    )
    enregistrer_audit(classe.etablissement, par, "bareme.derogation", derogation,
                      apres={"bareme": bareme, "coefficient": coefficient, "exclue": exclue})
    return derogation


@transaction.atomic
def affecter_enseignant(appartenance, matiere_niveau, classe=None, par=None):
    appartenance = Appartenance.sans_filtre.select_for_update().get(pk=appartenance.pk)
    if (
        appartenance.etablissement_id != matiere_niveau.etablissement_id
        or appartenance.role.etablissement_id != appartenance.etablissement_id
        or matiere_niveau.annee.etablissement_id != matiere_niveau.etablissement_id
        or matiere_niveau.niveau.etablissement_id != matiere_niveau.etablissement_id
        or matiere_niveau.matiere.etablissement_id != matiere_niveau.etablissement_id
    ):
        raise ErreurMetier("L'enseignant et la matière n'appartiennent pas au même établissement.")
    if not verifier_permission(appartenance.utilisateur, appartenance, "evaluations.saisir"):
        raise ErreurMetier("Ce membre n'a pas le rôle d'enseignant (permission de saisie des notes).")
    if classe is not None:
        if classe.etablissement_id != matiere_niveau.etablissement_id:
            raise ErreurMetier("La classe appartient à un autre établissement.")
        if classe.niveau_id != matiere_niveau.niveau_id or classe.annee_id != matiere_niveau.annee_id:
            raise ErreurMetier("La classe ne correspond pas au niveau et à l'année de la matière.")
        if not matiere_enseignee(matiere_niveau, classe):
            raise ErreurMetier("Cette matière n'est pas enseignée dans cette classe.")
    if AffectationEnseignant.sans_filtre.filter(
        appartenance=appartenance, matiere_niveau=matiere_niveau, classe=classe
    ).exists():
        raise ErreurMetier("Cette affectation existe déjà.")
    affectation = AffectationEnseignant.sans_filtre.create(
        etablissement=matiere_niveau.etablissement, appartenance=appartenance,
        matiere_niveau=matiere_niveau, classe=classe,
    )
    enregistrer_audit(matiere_niveau.etablissement, par, "affectation.creation", affectation)
    return affectation


@transaction.atomic
def desaffecter_enseignant(affectation, par=None):
    affectation = AffectationEnseignant.sans_filtre.select_for_update().get(pk=affectation.pk)
    Configuration = apps.get_model("evaluations", "ConfigurationEvaluation")
    if Configuration.sans_filtre.filter(affectation=affectation).exists():
        raise ErreurMetier(
            "Cette affectation est utilisée par une configuration d’évaluation. "
            "Elle ne peut pas être retirée afin de préserver l’historique des résultats."
        )
    Creneau = apps.get_model("emploi_du_temps", "Creneau")
    if Creneau.sans_filtre.filter(affectation=affectation).exists():
        raise ErreurMetier(
            "Cette affectation possède des créneaux d’emploi du temps. "
            "Retirez d’abord ces créneaux pour éviter de les supprimer avec le cours."
        )
    avant = {
        "enseignant": affectation.appartenance.utilisateur.nom_affiche,
        "matiere": affectation.matiere_niveau.matiere.nom,
        "niveau": affectation.matiere_niveau.niveau.nom,
        "classe": affectation.classe.nom if affectation.classe_id else None,
    }
    enregistrer_audit(
        affectation.etablissement, par, "affectation.suppression", affectation, avant=avant
    )
    affectation.delete()
    return affectation


@transaction.atomic
def dupliquer_matieres_niveaux(source, cible):
    """Copie barèmes et coefficients d'une année vers une autre (sans écraser l'existant)."""
    copiees = 0
    for element in MatiereNiveau.sans_filtre.filter(annee=source):
        _, creee = MatiereNiveau.sans_filtre.get_or_create(
            etablissement=element.etablissement, annee=cible, niveau=element.niveau, matiere=element.matiere,
            defaults={"bareme": element.bareme, "coefficient": element.coefficient},
        )
        copiees += int(creee)
    return copiees


def _verifier_cible_pedagogique(etablissement, enseignant, classe, matiere_niveau, tout=False):
    if not (etablissement.pk == classe.etablissement_id == matiere_niveau.etablissement_id):
        raise ErreurMetier("La classe, la matière et l'établissement doivent correspondre.")
    if classe.niveau_id != matiere_niveau.niveau_id or classe.annee_id != matiere_niveau.annee_id:
        raise ErreurMetier("La matière n'appartient pas à la classe ou à son année.")
    from applications.cahier.services import paires_accessibles

    if (classe.pk, matiere_niveau.pk) not in paires_accessibles(etablissement, enseignant, tout):
        raise ErreurMetier("Vous n'êtes pas affecté à cette matière et à cette classe.")


@transaction.atomic
def creer_ressource(etablissement, enseignant, classe, matiere_niveau, titre, description, fichier, tout=False, par=None):
    if fichier is None:
        raise ErreurMetier("Le fichier de la ressource est obligatoire.")
    _verifier_cible_pedagogique(etablissement, enseignant, classe, matiere_niveau, tout)
    ressource = RessourcePedagogique.sans_filtre.create(
        etablissement=etablissement, enseignant=enseignant, classe=classe,
        matiere_niveau=matiere_niveau, titre=titre.strip(),
        description=(description or "").strip(), fichier=fichier,
    )
    enregistrer_audit(
        etablissement, par or enseignant.utilisateur, "pedagogie.ressource_creation",
        ressource, apres={"classe": classe.pk, "matiere": matiere_niveau.pk},
    )
    return ressource


@transaction.atomic
def creer_quiz(
    etablissement, enseignant, classe, matiere_niveau, titre, description,
    questions, date_limite=None, nombre_tentatives_max=1, tout=False, par=None,
):
    _verifier_cible_pedagogique(etablissement, enseignant, classe, matiere_niveau, tout)
    if not titre.strip():
        raise ErreurMetier("Le titre du quiz est obligatoire.")
    if not 1 <= nombre_tentatives_max <= 10:
        raise ErreurMetier("Le nombre de tentatives doit être compris entre 1 et 10.")
    if not isinstance(questions, list) or not questions or len(questions) > 100:
        raise ErreurMetier("Un quiz doit comporter entre 1 et 100 questions.")

    validees = []
    for question in questions:
        texte = str(question.get("texte", "")).strip()
        choix = question.get("choix")
        bonne_reponse = question.get("bonne_reponse")
        if not texte or not isinstance(choix, list) or len(choix) < 2:
            raise ErreurMetier("Chaque question doit avoir un énoncé et au moins deux choix.")
        choix_nets = [str(option).strip() for option in choix]
        if any(not option for option in choix_nets) or len(set(choix_nets)) != len(choix_nets):
            raise ErreurMetier("Les choix d'une question doivent être remplis et uniques.")
        if isinstance(bonne_reponse, bool) or not isinstance(bonne_reponse, int) or not 0 <= bonne_reponse < len(choix_nets):
            raise ErreurMetier("Chaque question doit désigner un choix correct valide.")
        validees.append((texte, choix_nets, bonne_reponse))

    quiz = Quiz.sans_filtre.create(
        etablissement=etablissement, enseignant=enseignant, classe=classe,
        matiere_niveau=matiere_niveau, titre=titre.strip(),
        description=(description or "").strip(), date_limite=date_limite,
        nombre_tentatives_max=nombre_tentatives_max,
    )
    for ordre, (texte, choix, bonne_reponse) in enumerate(validees, start=1):
        question = QuestionQuiz.sans_filtre.create(
            etablissement=etablissement, quiz=quiz, texte=texte, ordre=ordre,
        )
        for ordre_choix, option in enumerate(choix, start=1):
            ChoixQuestion.sans_filtre.create(
                etablissement=etablissement, question=question, texte=option,
                correct=ordre_choix - 1 == bonne_reponse, ordre=ordre_choix,
            )
    enregistrer_audit(
        etablissement, par or enseignant.utilisateur, "pedagogie.quiz_creation",
        quiz, apres={"classe": classe.pk, "questions": len(validees)},
    )
    return quiz


def inscription_apprenant_pour_quiz(quiz, utilisateur):
    from applications.apprenants.models import Inscription

    return Inscription.objects.filter(
        apprenant__utilisateur=utilisateur, classe=quiz.classe,
        annee=quiz.classe.annee, statut=Inscription.Statut.VALIDEE,
    ).first()


@transaction.atomic
def soumettre_quiz(quiz, inscription, reponses, par):
    quiz = Quiz.sans_filtre.select_for_update().get(pk=quiz.pk)
    if not quiz.ouvert:
        raise ErreurMetier("Ce quiz n'est plus ouvert.")
    if quiz.date_limite and timezone.now() > quiz.date_limite:
        raise ErreurMetier("La date limite de ce quiz est dépassée.")
    if inscription.etablissement_id != quiz.etablissement_id or inscription.classe_id != quiz.classe_id:
        raise ErreurMetier("Cette inscription ne permet pas de répondre à ce quiz.")
    if inscription.statut != inscription.Statut.VALIDEE:
        raise ErreurMetier("Seule une inscription validée peut répondre à ce quiz.")
    if TentativeQuiz.sans_filtre.filter(quiz=quiz, inscription=inscription).count() >= quiz.nombre_tentatives_max:
        raise ErreurMetier("Le nombre maximal de tentatives pour ce quiz est atteint.")

    questions = list(QuestionQuiz.sans_filtre.filter(quiz=quiz).prefetch_related("choix"))
    if not questions:
        raise ErreurMetier("Ce quiz ne contient aucune question.")
    tentative = TentativeQuiz.sans_filtre.create(
        etablissement=quiz.etablissement, quiz=quiz, inscription=inscription,
    )
    score = 0
    for question in questions:
        valeur = reponses.get(str(question.pk), "")
        choix = None
        if valeur:
            try:
                choix = next(option for option in question.choix.all() if option.pk == int(valeur))
            except (StopIteration, TypeError, ValueError):
                raise ErreurMetier("Une réponse sélectionnée n'appartient pas à cette question.")
            if choix.correct:
                score += 1
        ReponseQuiz.sans_filtre.create(
            etablissement=quiz.etablissement, tentative=tentative, question=question, choix=choix,
        )
    tentative.score = score
    tentative.save(update_fields=["score"])
    enregistrer_audit(
        quiz.etablissement, par, "pedagogie.quiz_soumission", tentative,
        apres={"score": score, "total": len(questions)},
    )
    return tentative
