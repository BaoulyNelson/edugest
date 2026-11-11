"""Services métier du noyau."""
from django.db import transaction

from .contexte import sans_isolation
from .exceptions import ErreurMetier
from .models import (
    Appartenance, Etablissement, JournalAudit, ParametresEtablissement, Role,
    SequenceNumerotation, TypeEtablissement, Utilisateur, VocabulaireInstitutionnel,
)
from .permissions import ROLES_PAR_DEFAUT

VOCABULAIRE_PAR_TYPE = {
    TypeEtablissement.SCOLAIRE: {
        "periode": ("Trimestre", "Trimestres"),
        "niveau": ("Niveau", "Niveaux"),
        "classe": ("Classe", "Classes"),
    },
    TypeEtablissement.UNIVERSITAIRE: {
        "periode": ("Semestre", "Semestres"),
        "faculte": ("Faculté", "Facultés"),
        "programme": ("Programme", "Programmes"),
        "niveau": ("Année d'études", "Années d'études"),
    },
    TypeEtablissement.PROFESSIONNEL: {
        "periode": ("Session", "Sessions"),
        "niveau": ("Parcours", "Parcours"),
        "classe": ("Atelier", "Ateliers"),
    },
}


@sans_isolation
@transaction.atomic
def creer_etablissement(nom, type_etablissement, code_plan="ESSAI"):
    """Crée un établissement avec ses paramètres, ses rôles et son vocabulaire par défaut."""
    etablissement = Etablissement.objects.create(nom=nom, type=type_etablissement)
    ParametresEtablissement.objects.create(
        etablissement=etablissement,
        nombre_periodes_par_annee=2 if type_etablissement == TypeEtablissement.UNIVERSITAIRE else 3,
    )
    from .saas import ouvrir_abonnement_essai

    ouvrir_abonnement_essai(etablissement, code_plan=code_plan)
    for nom_role, codes in ROLES_PAR_DEFAUT.items():
        Role.sans_filtre.create(etablissement=etablissement, nom=nom_role, codes=list(codes))
    for cle, (singulier, pluriel) in VOCABULAIRE_PAR_TYPE[type_etablissement].items():
        VocabulaireInstitutionnel.sans_filtre.create(
            etablissement=etablissement, cle=cle, libelle_singulier=singulier, libelle_pluriel=pluriel
        )
    return etablissement


def vocabulaire(etablissement, cle, pluriel=False):
    """Libellé institutionnel configurable (ex. « Faculté » ou « Département »)."""
    entree = VocabulaireInstitutionnel.sans_filtre.filter(etablissement=etablissement, cle=cle).first()
    if entree:
        return entree.libelle_pluriel if pluriel else entree.libelle_singulier
    defaut = VOCABULAIRE_PAR_TYPE.get(etablissement.type, {}).get(cle, (cle.capitalize(), cle.capitalize()))
    return defaut[1] if pluriel else defaut[0]


@sans_isolation
@transaction.atomic
def creer_membre(etablissement, nom_utilisateur, email, mot_de_passe, nom_role, prenom="", nom=""):
    """Crée (ou rattache) un utilisateur à un établissement avec le rôle indiqué."""
    role = Role.sans_filtre.filter(etablissement=etablissement, nom=nom_role).first()
    if role is None:
        raise ErreurMetier(f"Le rôle « {nom_role} » n'existe pas dans cet établissement.")
    utilisateur = Utilisateur.objects.filter(email__iexact=email).first()
    if utilisateur is None:
        utilisateur = Utilisateur.objects.create_user(
            username=nom_utilisateur, email=email, password=mot_de_passe, first_name=prenom, last_name=nom
        )
    if Appartenance.sans_filtre.filter(utilisateur=utilisateur, etablissement=etablissement).exists():
        raise ErreurMetier("Cet utilisateur fait déjà partie de l'établissement.")
    return Appartenance.sans_filtre.create(utilisateur=utilisateur, etablissement=etablissement, role=role)


def verifier_permission(utilisateur, appartenance, code):
    """Vérifie une permission métier portée par l'appartenance active de l'utilisateur."""
    if utilisateur is None or not utilisateur.is_authenticated:
        return False
    if (
        appartenance is None
        or not appartenance.actif
        or appartenance.utilisateur_id != utilisateur.pk
    ):
        return False
    return code in appartenance.role.codes


def nom_plateforme():
    """Renvoie le nom public configuré, avec le nom historique comme solution de repli."""
    from .models import ConfigurationPlateforme

    configuration = ConfigurationPlateforme.objects.filter(pk=1).first()
    return configuration.nom if configuration and configuration.nom else "EduGest"


@transaction.atomic
def servir_numero(etablissement, cle):
    """Incrémente et renvoie le prochain numéro d'une séquence (sans doublon, verrouillé)."""
    sequence, _ = SequenceNumerotation.sans_filtre.select_for_update().get_or_create(
        etablissement=etablissement, cle=cle
    )
    sequence = SequenceNumerotation.sans_filtre.select_for_update().get(pk=sequence.pk)
    sequence.derniere_valeur += 1
    sequence.save(update_fields=["derniere_valeur"])
    return sequence.derniere_valeur


def enregistrer_audit(etablissement, utilisateur, action, objet=None, avant=None, apres=None, motif=""):
    """Ajoute une ligne au journal d'audit."""
    return JournalAudit.objects.create(
        etablissement=etablissement,
        utilisateur=utilisateur if getattr(utilisateur, "pk", None) else None,
        action=action,
        objet_type=objet.__class__.__name__ if objet is not None else "",
        objet_id=str(objet.pk) if objet is not None else "",
        avant=avant,
        apres=apres,
        motif=motif,
    )
