from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from applications.academique.models import Classe
from applications.academique.services import annee_active
from applications.apprenants.models import Apprenant, Inscription, LienResponsable
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit, verifier_permission
from applications.pedagogie.models import AffectationEnseignant

from .models import AppelPresence, LignePresence, NotificationPresence


def classes_accessibles(etablissement, appartenance, utilisateur):
    annee = annee_active(etablissement)
    if annee is None:
        return Classe.objects.none()
    if verifier_permission(utilisateur, appartenance, "presences.consulter"):
        return Classe.objects.filter(annee=annee).select_related("niveau")
    if appartenance is None:
        return Classe.objects.none()
    affectations = AffectationEnseignant.objects.filter(
        appartenance=appartenance, matiere_niveau__annee=annee,
    )
    classes_directes = affectations.filter(classe__isnull=False).values_list("classe_id", flat=True)
    niveaux = affectations.filter(classe__isnull=True).values_list("matiere_niveau__niveau_id", flat=True)
    return Classe.objects.filter(annee=annee).filter(
        Q(pk__in=classes_directes) | Q(niveau_id__in=niveaux)
    ).select_related("niveau").distinct()


def inscrits(classe):
    return Inscription.objects.filter(
        etablissement=classe.etablissement,
        annee=classe.annee,
        classe=classe,
        statut=Inscription.Statut.VALIDEE,
    ).select_related("apprenant").order_by("apprenant__nom", "apprenant__prenoms")


def valider_date_appel(classe, jour):
    if jour > timezone.localdate():
        raise ErreurMetier("Il n'est pas possible de faire l'appel pour une date future.")
    if jour < classe.annee.date_debut or jour > classe.annee.date_fin:
        raise ErreurMetier("La date de l'appel doit être comprise dans l'année académique de la classe.")
    if not classe.annee.est_active:
        raise ErreurMetier("L'appel ne peut être modifié que pour une année académique active.")


def _alerter_familles(inscription, statut, jour, motif):
    apprenant = inscription.apprenant
    liens = LienResponsable.objects.filter(
        etablissement=inscription.etablissement,
        apprenant=apprenant,
        responsable__utilisateur__isnull=False,
    ).select_related("responsable__utilisateur")
    destinataires = {lien.responsable.utilisateur for lien in liens}
    if apprenant.utilisateur_id:
        destinataires.add(apprenant.utilisateur)
    verbe = {
        LignePresence.Statut.ABSENT: "absent(e)",
        LignePresence.Statut.RETARD: "en retard",
        LignePresence.Statut.JUSTIFIE: "justifié(e)",
    }[statut]
    texte = f"Le {jour:%d/%m/%Y} · {inscription.classe}"
    if motif:
        texte = f"{texte} · {motif[:150]}"
    for destinataire in destinataires:
        NotificationPresence.sans_filtre.create(
            etablissement=inscription.etablissement,
            destinataire=destinataire,
            titre=f"{apprenant} était {verbe}",
            texte=texte,
        )


def obtenir_appel(classe, jour, enseignant):
    valider_date_appel(classe, jour)
    appel, _ = AppelPresence.objects.get_or_create(
        etablissement=classe.etablissement, classe=classe, date=jour,
        defaults={"enseignant": enseignant},
    )
    return appel


@transaction.atomic
def enregistrer_appel(appel, saisies, appartenance, acteur):
    if not verifier_permission(acteur, appartenance, "presences.saisir"):
        raise ErreurMetier("Vous n'avez pas l'autorisation d'enregistrer un appel.")
    if appartenance is not None and appartenance.etablissement_id != appel.etablissement_id:
        raise ErreurMetier("Cette appartenance ne correspond pas à l'établissement de l'appel.")
    if not classes_accessibles(appel.etablissement, appartenance, acteur).filter(
        pk=appel.classe_id,
    ).exists():
        raise ErreurMetier("Vous n'êtes pas affecté à cette classe.")
    valider_date_appel(appel.classe, appel.date)
    valides = {inscription.pk: inscription for inscription in inscrits(appel.classe)}
    existantes = {ligne.inscription_id: ligne for ligne in appel.lignes.select_for_update()}
    maintenant = set()
    for inscription_id, (statut, motif) in saisies.items():
        inscription = valides.get(inscription_id)
        if inscription is None:
            raise ErreurMetier("Un apprenant sélectionné n'est pas inscrit et validé dans cette classe.")
        if statut not in LignePresence.Statut.values:
            raise ErreurMetier("Un statut de présence est invalide.")
        ligne = existantes.get(inscription_id) or LignePresence(
            etablissement=appel.etablissement, appel=appel, inscription=inscription,
        )
        ancien_statut = ligne.statut if ligne.pk else None
        ligne.statut = statut
        ligne.motif = (motif or "").strip()[:150]
        ligne.save()
        if statut in (
            LignePresence.Statut.ABSENT,
            LignePresence.Statut.RETARD,
            LignePresence.Statut.JUSTIFIE,
        ) and ancien_statut != statut:
            _alerter_familles(inscription, statut, appel.date, ligne.motif)
        maintenant.add(inscription_id)
    if not valides:
        raise ErreurMetier("Aucun apprenant validé n'est inscrit dans cette classe.")
    avant = {"lignes": len(existantes)}
    apres = {"lignes": len(maintenant), "absents": sum(1 for _, (statut, _) in saisies.items() if statut == LignePresence.Statut.ABSENT)}
    enregistrer_audit(appel.etablissement, acteur, "presence.appel", appel, avant=avant, apres=apres)
    return apres["absents"]


def historique(classe=None, limite=100):
    appels = AppelPresence.objects.select_related("classe__niveau", "enseignant").annotate(
        presents=Count("lignes", filter=Q(lignes__statut=LignePresence.Statut.PRESENT)),
        absents=Count("lignes", filter=Q(lignes__statut=LignePresence.Statut.ABSENT)),
        retards=Count("lignes", filter=Q(lignes__statut=LignePresence.Statut.RETARD)),
        justifies=Count("lignes", filter=Q(lignes__statut=LignePresence.Statut.JUSTIFIE)),
    )
    if classe is not None:
        appels = appels.filter(classe=classe)
    return appels.order_by("-date", "-pk")[:limite]


def bilan_apprenant(apprenant):
    lignes = LignePresence.objects.filter(
        inscription__apprenant=apprenant,
    ).select_related("appel__classe", "inscription__annee").order_by("-appel__date", "-pk")
    return {
        "absences": lignes.filter(statut=LignePresence.Statut.ABSENT).count(),
        "retards": lignes.filter(statut=LignePresence.Statut.RETARD).count(),
        "justifiees": lignes.filter(statut=LignePresence.Statut.JUSTIFIE).count(),
        "detail": list(lignes.exclude(statut=LignePresence.Statut.PRESENT)[:60]),
    }


def apprenants_associes(utilisateur, etablissement):
    ids_apprenants = set(
        Apprenant.objects.filter(etablissement=etablissement, utilisateur=utilisateur)
        .values_list("pk", flat=True)
    )
    ids_apprenants.update(
        LienResponsable.objects.filter(
            etablissement=etablissement, responsable__utilisateur=utilisateur,
        ).values_list("apprenant_id", flat=True)
    )
    return Apprenant.objects.filter(etablissement=etablissement, pk__in=ids_apprenants).order_by("nom", "prenoms")
