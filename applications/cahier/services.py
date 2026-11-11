import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from applications.academique.models import Classe
from applications.academique.services import annee_active
from applications.apprenants.models import Inscription, LienResponsable
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit
from applications.pedagogie.models import AffectationEnseignant, MatiereNiveau

from .models import (
    Devoir, EntreeCahier, NotificationCahier, PieceJointeDevoir, PieceJointeRemise, Remise,
)

logger = logging.getLogger(__name__)


def paires_accessibles(etablissement, appartenance, tout=False):
    annee = annee_active(etablissement)
    if annee is None:
        return set()
    classes = Classe.objects.filter(etablissement=etablissement, annee=annee)
    if tout:
        matieres_par_niveau = {}
        for matiere in MatiereNiveau.objects.filter(etablissement=etablissement, annee=annee):
            matieres_par_niveau.setdefault(matiere.niveau_id, []).append(matiere.pk)
        return {
            (classe.pk, matiere_id)
            for classe in classes
            for matiere_id in matieres_par_niveau.get(classe.niveau_id, ())
        }
    if appartenance is None:
        return set()
    affectations = AffectationEnseignant.objects.filter(
        etablissement=etablissement,
        appartenance=appartenance,
        matiere_niveau__annee=annee,
    ).select_related("matiere_niveau")
    paires = set()
    for affectation in affectations:
        classes_affectees = (
            classes.filter(pk=affectation.classe_id)
            if affectation.classe_id
            else classes.filter(niveau_id=affectation.matiere_niveau.niveau_id)
        )
        paires.update((classe.pk, affectation.matiere_niveau_id) for classe in classes_affectees)
    return paires


def classes_accessibles(etablissement, appartenance, tout=False):
    ids = {classe_id for classe_id, _ in paires_accessibles(etablissement, appartenance, tout)}
    return Classe.objects.filter(etablissement=etablissement, pk__in=ids).select_related("niveau", "annee")


def inscriptions_de_l_utilisateur(utilisateur, etablissement):
    return Inscription.objects.filter(
        etablissement=etablissement,
        annee__statut="ACTIVE",
        statut=Inscription.Statut.VALIDEE,
    ).filter(
        Q(apprenant__utilisateur=utilisateur)
        | Q(apprenant__liens_responsables__responsable__utilisateur=utilisateur)
    ).select_related("apprenant", "classe").distinct()


def classes_de_l_utilisateur(utilisateur, etablissement):
    return inscriptions_de_l_utilisateur(utilisateur, etablissement).exclude(
        classe__isnull=True,
    ).values_list("classe_id", flat=True)


def _verifier_cible(etablissement, classe, matiere_niveau, paires):
    if (
        classe.etablissement_id != etablissement.pk
        or matiere_niveau.etablissement_id != etablissement.pk
        or classe.annee_id != matiere_niveau.annee_id
        or classe.niveau_id != matiere_niveau.niveau_id
    ):
        raise ErreurMetier("La classe et la matière ne correspondent pas à la même année et au même niveau.")
    if (classe.pk, matiere_niveau.pk) not in paires:
        raise ErreurMetier("Vous n'êtes pas affecté à cette matière et à cette classe.")
    if not classe.annee.est_active:
        raise ErreurMetier("Le cahier de textes ne peut être modifié que pour une année académique active.")


@transaction.atomic
def creer_entree(etablissement, appartenance, donnees, tout=False, acteur=None):
    classe = donnees["classe"]
    matiere_niveau = donnees["matiere_niveau"]
    _verifier_cible(etablissement, classe, matiere_niveau, paires_accessibles(etablissement, appartenance, tout))
    entree = EntreeCahier.objects.create(
        etablissement=etablissement,
        enseignant=appartenance,
        **donnees,
    )
    enregistrer_audit(
        etablissement, acteur or getattr(appartenance, "utilisateur", None), "cahier.seance", entree,
    )
    return entree


@transaction.atomic
def publier_devoir(etablissement, appartenance, donnees, tout=False, acteur=None):
    classe = donnees["classe"]
    matiere_niveau = donnees["matiere_niveau"]
    fichiers = donnees.pop("fichiers", None) or []
    _verifier_cible(etablissement, classe, matiere_niveau, paires_accessibles(etablissement, appartenance, tout))
    devoir = Devoir.objects.create(
        etablissement=etablissement,
        enseignant=appartenance,
        fichier=fichiers[0] if fichiers else None,
        **donnees,
    )
    for fichier in fichiers[1:]:
        PieceJointeDevoir.objects.create(
            etablissement=etablissement,
            devoir=devoir,
            fichier=fichier,
            nom=fichier.name,
        )
    enregistrer_audit(
        etablissement, acteur or getattr(appartenance, "utilisateur", None), "cahier.devoir", devoir,
    )
    inscriptions = Inscription.objects.filter(
        etablissement=etablissement,
        classe=classe,
        annee=classe.annee,
        statut=Inscription.Statut.VALIDEE,
    ).select_related("apprenant")
    destinataires = {
        lien.responsable.utilisateur
        for lien in LienResponsable.objects.filter(
            etablissement=etablissement,
            apprenant__inscriptions__in=inscriptions,
            responsable__utilisateur__isnull=False,
        ).select_related("responsable__utilisateur")
    }
    destinataires.update(
        inscription.apprenant.utilisateur
        for inscription in inscriptions
        if inscription.apprenant.utilisateur_id
    )
    NotificationCahier.objects.bulk_create([
        NotificationCahier(
            etablissement=etablissement,
            destinataire=destinataire,
            titre=f"Nouveau devoir : {devoir.titre}",
            texte=(
                f"{devoir.matiere_niveau.matiere} · à remettre le "
                f"{devoir.date_limite:%d/%m/%Y} à {devoir.heure_limite:%H:%M}"
            ),
            url=f"/cahier/devoirs/{devoir.pk}/",
        )
        for destinataire in destinataires
    ])
    return devoir


@transaction.atomic
def deposer_travail(devoir, inscription, fichiers, commentaire=""):
    if (
        devoir.etablissement_id != inscription.etablissement_id
        or devoir.classe_id != inscription.classe_id
        or inscription.annee_id != devoir.classe.annee_id
        or inscription.statut != Inscription.Statut.VALIDEE
        or not devoir.remise_numerique
    ):
        raise ErreurMetier("Cette remise n'est pas autorisée pour cette inscription.")
    remise = Remise.objects.filter(devoir=devoir, inscription=inscription).first()
    ancien_fichier = remise.fichier if remise else None
    anciennes_pieces = list(remise.pieces_jointes.all()) if remise else []
    maintenant = timezone.now()
    en_retard = maintenant > devoir.echeance
    if en_retard and remise is None and not devoir.accepter_remises_tardives:
        raise ErreurMetier("La date limite est dépassée et les remises tardives sont désactivées.")
    if en_retard and remise is not None and not devoir.modifier_apres_echeance:
        raise ErreurMetier("Les modifications de cette remise sont désactivées après la date limite.")
    if not fichiers:
        raise ErreurMetier("Ajoutez au moins un fichier à votre remise.")
    if remise is None:
        remise = Remise(
            etablissement=devoir.etablissement,
            devoir=devoir,
            inscription=inscription,
        )
    remise.fichier = fichiers[0]
    remise.commentaire = (commentaire or "").strip()
    remise.en_retard = en_retard
    remise.remise_le = maintenant
    remise.note = None
    remise.appreciation = ""
    remise.corrige_le = None
    remise.correcteur = None
    remise.save()
    for fichier in fichiers[1:]:
        PieceJointeRemise.objects.create(
            etablissement=devoir.etablissement,
            remise=remise,
            fichier=fichier,
            nom=fichier.name,
        )
    if ancien_fichier and ancien_fichier.name != remise.fichier.name:
        try:
            ancien_fichier.delete(save=False)
        except PermissionError:
            logger.warning(
                "Ancien fichier de remise non supprimé après remplacement : %s",
                ancien_fichier.name,
                exc_info=True,
            )
    for ancienne_piece in anciennes_pieces:
        ancienne_piece.fichier.delete(save=False)
        ancienne_piece.delete()
    enregistrer_audit(
        devoir.etablissement,
        inscription.apprenant.utilisateur,
        "cahier.remise",
        remise,
        apres={"en_retard": remise.en_retard},
    )
    if devoir.enseignant_id and devoir.enseignant.utilisateur_id:
        NotificationCahier.objects.create(
            etablissement=devoir.etablissement,
            destinataire=devoir.enseignant.utilisateur,
            titre=f"Travail remis : {devoir.titre}",
            texte=f"{inscription.apprenant} a remis son travail.",
            url=f"/cahier/devoirs/{devoir.pk}/",
        )
    return remise


def evaluer_remise(remise, appreciation, acteur, note=None):
    remise.appreciation = appreciation.strip()
    champs = ["appreciation"]
    if note is not None:
        if note < 0 or note > remise.devoir.bareme:
            raise ErreurMetier(f"La note doit être comprise entre 0 et {remise.devoir.bareme}.")
        remise.note = note
        remise.corrige_le = timezone.now()
        remise.correcteur = acteur
        champs.extend(["note", "corrige_le", "correcteur"])
    remise.save(update_fields=champs)
    enregistrer_audit(
        remise.etablissement,
        acteur,
        "cahier.appreciation",
        remise,
        apres={"appreciation": remise.appreciation, "note": str(remise.note) if remise.note is not None else None},
    )
    apprenant = remise.inscription.apprenant
    if apprenant.utilisateur_id:
        NotificationCahier.objects.create(
            etablissement=remise.etablissement,
            destinataire=apprenant.utilisateur,
            titre=f"Travail corrigé : {remise.devoir.titre}",
            texte=remise.appreciation,
            url=f"/cahier/devoirs/{remise.devoir_id}/",
        )
    return remise
