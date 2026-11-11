"""Libellés et indicateurs de fonctionnalités propres à chaque profil."""
from applications.noyau.models import TypeEtablissement
from django.utils.translation import gettext_lazy as _


LIBELLES_PAR_TYPE = {
    TypeEtablissement.SCOLAIRE: {
        "apprenants": _("Élèves"),
        "apprenant": _("Élève"),
        "groupes": _("Classes"),
        "groupe": _("Classe"),
        "cours": _("Matières"),
        "cours_singulier": _("Matière"),
        "evaluations": _("Bulletins"),
        "evaluation": _("Bulletin"),
    },
    TypeEtablissement.UNIVERSITAIRE: {
        "apprenants": _("Étudiants"),
        "apprenant": _("Étudiant"),
        "groupes": _("Programmes / Filières"),
        "groupe": _("Programme / Filière"),
        "cours": _("Unités d'Enseignement (UE)"),
        "cours_singulier": _("Unité d'Enseignement (UE)"),
        "evaluations": _("Relevés de notes / Crédits"),
        "evaluation": _("Relevé de notes / Crédit"),
    },
    TypeEtablissement.PROFESSIONNEL: {
        "apprenants": _("Stagiaires / Apprenants"),
        "apprenant": _("Stagiaire / Apprenant"),
        "groupes": _("Sessions / Ateliers"),
        "groupe": _("Session / Atelier"),
        "cours": _("Modules pratiques"),
        "cours_singulier": _("Module pratique"),
        "evaluations": _("Attestations de compétences"),
        "evaluation": _("Attestation de compétences"),
    },
}

FONCTIONNALITES_PAR_TYPE = {
    TypeEtablissement.SCOLAIRE: {
        "parents_tuteurs": True,
        "appels_quotidiens": True,
        "credits_ects": False,
        "prerequis_modules": False,
        "planning_flexible": False,
        "attestations_competences": False,
    },
    TypeEtablissement.UNIVERSITAIRE: {
        "parents_tuteurs": False,
        "appels_quotidiens": False,
        "credits_ects": True,
        "prerequis_modules": True,
        "planning_flexible": False,
        "attestations_competences": False,
    },
    TypeEtablissement.PROFESSIONNEL: {
        "parents_tuteurs": False,
        "appels_quotidiens": False,
        "credits_ects": False,
        "prerequis_modules": False,
        "planning_flexible": True,
        "attestations_competences": True,
    },
}


def profil_etablissement(type_etablissement=None):
    """Renvoie les libellés et modules actifs, avec le profil scolaire par défaut."""
    type_etablissement = type_etablissement or TypeEtablissement.SCOLAIRE
    return {
        "libelles": LIBELLES_PAR_TYPE.get(
            type_etablissement, LIBELLES_PAR_TYPE[TypeEtablissement.SCOLAIRE]
        ).copy(),
        "fonctionnalites": FONCTIONNALITES_PAR_TYPE.get(
            type_etablissement, FONCTIONNALITES_PAR_TYPE[TypeEtablissement.SCOLAIRE]
        ).copy(),
    }
