from django.db import transaction
from django.utils import timezone

from applications.academique.services import annee_active
from applications.academique.models import AnneeAcademique
from applications.apprenants.models import Inscription
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit
from applications.pedagogie.models import AffectationEnseignant

from .models import Creneau, JOURS, Salle


def conflits(annee, affectation, jour, debut, fin, salle=None, exclure_pk=None):
    recouvrements = Creneau.objects.filter(
        etablissement=annee.etablissement,
        annee=annee,
        jour=jour,
        heure_debut__lt=fin,
        heure_fin__gt=debut,
    ).select_related("affectation__appartenance__utilisateur", "affectation__classe", "affectation__matiere_niveau__matiere")
    if exclure_pk:
        recouvrements = recouvrements.exclude(pk=exclure_pk)
    problemes = []
    for autre in recouvrements:
        plage = f"{autre.heure_debut:%H:%M}-{autre.heure_fin:%H:%M}"
        if autre.affectation.classe_id == affectation.classe_id:
            problemes.append(
                f"La classe {affectation.classe} a déjà cours de "
                f"{autre.affectation.matiere_niveau.matiere} ({plage})."
            )
        if autre.affectation.appartenance_id == affectation.appartenance_id:
            problemes.append(
                f"{affectation.appartenance.utilisateur.nom_affiche} enseigne déjà "
                f"à {autre.affectation.classe} ({plage})."
            )
        if salle and autre.salle_id == salle.pk:
            problemes.append(f"La salle {salle} est déjà occupée ({plage}).")
    return problemes


@transaction.atomic
def creer_creneau(*, etablissement, affectation, jour, heure_debut, heure_fin, salle, acteur):
    if heure_fin <= heure_debut:
        raise ErreurMetier("L'heure de fin doit être postérieure à l'heure de début.")
    if jour not in dict(JOURS):
        raise ErreurMetier("Le jour choisi est invalide.")
    if affectation.etablissement_id != etablissement.pk:
        raise ErreurMetier("Cette affectation appartient à un autre établissement.")
    annee = affectation.matiere_niveau.annee
    annee_active_courante = annee_active(etablissement)
    if annee_active_courante is None or annee_active_courante.pk != annee.pk:
        raise ErreurMetier("Un créneau ne peut être créé que pour l'année académique active.")
    if affectation.classe_id is None:
        raise ErreurMetier("Une affectation à une classe est nécessaire pour créer un créneau.")
    if salle is not None and salle.etablissement_id != etablissement.pk:
        raise ErreurMetier("Cette salle appartient à un autre établissement.")
    if salle and salle.capacite:
        effectif = Inscription.objects.filter(
            etablissement=etablissement,
            classe=affectation.classe,
            statut=Inscription.Statut.VALIDEE,
            annee=annee,
        ).count()
        if effectif > salle.capacite:
            raise ErreurMetier(
                f"La salle {salle} ({salle.capacite} places) est trop petite "
                f"pour {affectation.classe} ({effectif} apprenants)."
            )
    AnneeAcademique.sans_filtre.select_for_update().get(pk=annee.pk)
    problemes = conflits(annee, affectation, jour, heure_debut, heure_fin, salle)
    if problemes:
        raise ErreurMetier(" ".join(problemes))
    creneau = Creneau.objects.create(
        etablissement=etablissement,
        annee=annee,
        affectation=affectation,
        jour=jour,
        heure_debut=heure_debut,
        heure_fin=heure_fin,
        salle=salle,
    )
    enregistrer_audit(etablissement, acteur, "emploi.creneau", creneau)
    return creneau


@transaction.atomic
def supprimer_creneau(creneau, acteur):
    if creneau.annee.statut != creneau.annee.Statut.ACTIVE:
        raise ErreurMetier("Seuls les créneaux de l'année active peuvent être supprimés.")
    enregistrer_audit(creneau.etablissement, acteur, "emploi.creneau_suppression", creneau)
    creneau.delete()


def regrouper_par_jour(creneaux, maintenant=None):
    maintenant = timezone.localtime(maintenant or timezone.now())
    jours = {}
    for creneau in creneaux:
        en_cours = (
            creneau.jour == maintenant.isoweekday()
            and creneau.heure_debut <= maintenant.time() < creneau.heure_fin
        )
        jours.setdefault(creneau.jour, []).append({"creneau": creneau, "en_cours": en_cours})
    noms = dict(JOURS)
    return [
        {
            "jour": jour,
            "nom": noms[jour],
            "aujourdhui": jour == maintenant.isoweekday(),
            "seances": seances,
        }
        for jour, seances in sorted(jours.items())
    ]


def _creneaux_actifs():
    return Creneau.objects.filter(annee__statut="ACTIVE").select_related(
        "affectation__appartenance__utilisateur",
        "affectation__matiere_niveau__matiere",
        "affectation__classe",
        "salle",
    )


def creneaux_de_classe(classe):
    return _creneaux_actifs().filter(affectation__classe=classe)


def creneaux_de_l_enseignant(appartenance, etablissement):
    return _creneaux_actifs().filter(
        etablissement=etablissement, affectation__appartenance=appartenance,
    )


def creneaux_de_la_famille(utilisateur, etablissement):
    from applications.cahier.services import classes_de_l_utilisateur

    return _creneaux_actifs().filter(
        etablissement=etablissement,
        affectation__classe_id__in=classes_de_l_utilisateur(utilisateur, etablissement),
    )
