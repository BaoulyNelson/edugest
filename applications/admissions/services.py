from django.db import transaction
from django.utils import timezone

from applications.academique.models import AnneeAcademique
from applications.apprenants import services as services_apprenants
from applications.apprenants.models import LienResponsable
from applications.noyau import saas
from applications.noyau.contexte import definir_etablissement_courant, reinitialiser_etablissement_courant
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance, Role
from applications.noyau.services import enregistrer_audit

from .models import Candidature


@transaction.atomic
def deposer_candidature(formulaire):
    candidature = formulaire.save(commit=False)
    token = definir_etablissement_courant(candidature.etablissement.pk)
    try:
        candidature.save()
    finally:
        reinitialiser_etablissement_courant(token)
    return candidature


@transaction.atomic
def accepter_candidature(candidature, auteur, url_base):
    candidature = Candidature.objects.select_for_update().select_related(
        "etablissement", "annee", "classe__niveau"
    ).get(pk=candidature.pk)
    if candidature.statut != Candidature.Statut.RECUE:
        raise ErreurMetier("Cette candidature a déjà été traitée.")
    if candidature.annee.statut != AnneeAcademique.Statut.ACTIVE:
        raise ErreurMetier("L’année de cette candidature n’est plus active.")

    token = definir_etablissement_courant(candidature.etablissement.pk)
    try:
        parent = services_apprenants.creer_responsable(
            candidature.etablissement,
            candidature.nom_parent,
            telephone=candidature.telephone_parent,
            email=candidature.email_parent,
        )
        apprenant = services_apprenants.creer_apprenant(
            candidature.etablissement,
            candidature.nom,
            candidature.prenoms,
            candidature.sexe,
            candidature.date_naissance,
            responsable=parent,
            lien=LienResponsable.Lien.TUTEUR,
            lieu_naissance=candidature.lieu_naissance,
        )
        inscription = services_apprenants.creer_inscription(
            candidature.etablissement, apprenant, candidature.classe.niveau, classe=candidature.classe, par=auteur
        )
        services_apprenants.decider_inscription(
            inscription, "VALIDER", auteur, motif=f"Acceptation de la candidature {candidature.reference}"
        )
        role_parent = Role.sans_filtre.get(etablissement=candidature.etablissement, nom="Parent")
        appartenance_parent = Appartenance.sans_filtre.select_related("utilisateur", "role").filter(
            etablissement=candidature.etablissement,
            utilisateur__email__iexact=candidature.email_parent,
        ).first()
        if appartenance_parent:
            if appartenance_parent.role_id != role_parent.pk or not appartenance_parent.actif:
                raise ErreurMetier("Le courriel du parent appartient déjà à un compte qui n’a pas le rôle Parent actif.")
            parent.utilisateur = appartenance_parent.utilisateur
            parent.save(update_fields=["utilisateur"])
            invitation = None
        else:
            invitation = saas.inviter(
                candidature.etablissement, candidature.email_parent, role_parent, auteur, url_base, responsable=parent
            )
        candidature.apprenant_cree = apprenant
        candidature.inscription_creee = inscription
        candidature.statut = Candidature.Statut.ACCEPTEE
        candidature.traitee_par = auteur
        candidature.traitee_le = timezone.now()
        candidature.save(update_fields=[
            "apprenant_cree", "inscription_creee", "statut", "traitee_par", "traitee_le",
        ])
        enregistrer_audit(
            candidature.etablissement, auteur, "admission.acceptation", candidature,
            apres={
                "reference": str(candidature.reference), "inscription": inscription.pk,
                "invitation": invitation.pk if invitation else None,
            },
        )
        return candidature, invitation
    finally:
        reinitialiser_etablissement_courant(token)


@transaction.atomic
def refuser_candidature(candidature, auteur, motif=""):
    candidature = Candidature.objects.select_for_update().get(pk=candidature.pk)
    if candidature.statut != Candidature.Statut.RECUE:
        raise ErreurMetier("Cette candidature a déjà été traitée.")
    candidature.statut = Candidature.Statut.REFUSEE
    candidature.traitee_par = auteur
    candidature.traitee_le = timezone.now()
    candidature.motif_decision = motif.strip()
    candidature.save(update_fields=["statut", "traitee_par", "traitee_le", "motif_decision"])
    enregistrer_audit(
        candidature.etablissement, auteur, "admission.refus", candidature, motif=candidature.motif_decision
    )
    return candidature
