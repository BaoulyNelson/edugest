"""Services de création, de confirmation et d'acceptation des comptes."""
import uuid

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from applications.noyau.contexte import sans_isolation
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance, Invitation, TypeEtablissement, Utilisateur
from applications.noyau.services import enregistrer_audit, nom_plateforme


def normaliser_email(email):
    return (email or "").strip().lower()


def _identifiant_unique():
    return f"u{uuid.uuid4().hex[:24]}"


def jeton_verification(utilisateur):
    return signing.dumps({"u": utilisateur.pk, "e": utilisateur.email}, salt="verification-courriel")


def envoyer_verification(utilisateur, url_base):
    from applications.noyau.saas import envoyer_courriel

    lien = f"{url_base}/verification/{jeton_verification(utilisateur)}/"
    plateforme = nom_plateforme()
    envoyer_courriel(
        utilisateur.email,
        f"Confirmez votre adresse e-mail - {plateforme}",
        f"Bonjour {utilisateur.first_name or ''},\n\nConfirmez votre adresse e-mail en ouvrant ce lien :\n"
        f"{lien}\n\nCe lien est valable 7 jours.\n\nL'équipe {plateforme}",
    )


def verifier_courriel(jeton):
    try:
        donnees = signing.loads(jeton, salt="verification-courriel", max_age=7 * 24 * 3600)
    except signing.BadSignature as erreur:
        raise ErreurMetier("Ce lien de confirmation est invalide ou expiré.") from erreur
    utilisateur = Utilisateur.objects.filter(pk=donnees["u"], email=donnees["e"]).first()
    if utilisateur is None:
        raise ErreurMetier("Ce lien de confirmation ne correspond à aucun compte.")
    utilisateur.email_verifie = True
    utilisateur.save(update_fields=["email_verifie"])
    return utilisateur


@transaction.atomic
def inscrire_utilisateur(prenom, nom, email, mot_de_passe, url_base=None, email_verifie=False, username=None):
    email = normaliser_email(email)
    if Utilisateur.objects.filter(email__iexact=email).exists():
        raise ErreurMetier(
            "Un compte existe déjà avec cette adresse e-mail. Connectez-vous ou réinitialisez votre mot de passe."
        )
    username = (username or _identifiant_unique()).strip()
    try:
        for validator in Utilisateur._meta.get_field("username").validators:
            validator(username)
    except ValidationError as erreur:
        raise ErreurMetier("Le nom d’utilisateur choisi n’est pas valide.") from erreur
    if Utilisateur.objects.filter(username__iexact=username).exists():
        raise ErreurMetier("Ce nom d’utilisateur est déjà utilisé.")
    utilisateur = Utilisateur.objects.create_user(
        username=username,
        email=email,
        password=mot_de_passe,
        first_name=prenom.strip(),
        last_name=nom.strip(),
        email_verifie=email_verifie,
    )
    if url_base and not email_verifie:
        envoyer_verification(utilisateur, url_base)
    return utilisateur


def invitation_par_jeton(jeton):
    invitation = Invitation.sans_filtre.select_related("etablissement", "role").filter(jeton=jeton).first()
    if invitation is None or not invitation.est_valide:
        raise ErreurMetier("Cette invitation est invalide, expirée ou a été révoquée.")
    return invitation


@sans_isolation
@transaction.atomic
def accepter_invitation(invitation, utilisateur):
    invitation = Invitation.sans_filtre.select_for_update().get(pk=invitation.pk)
    if not invitation.est_valide:
        raise ErreurMetier("Cette invitation est invalide, expirée ou a été révoquée.")
    if normaliser_email(utilisateur.email) != normaliser_email(invitation.email):
        raise ErreurMetier(
            f"Cette invitation est destinée à {invitation.email}. Connectez-vous avec cette adresse."
        )
    if Appartenance.sans_filtre.filter(utilisateur=utilisateur, etablissement=invitation.etablissement).exists():
        raise ErreurMetier("Vous faites déjà partie de cet établissement.")

    profil = None
    champs_a_enregistrer = ["utilisateur"]
    if invitation.role.nom == "Apprenant":
        profil = invitation.apprenant
        if profil is None or profil.etablissement_id != invitation.etablissement_id or profil.utilisateur_id:
            raise ErreurMetier("Le dossier apprenant associé à cette invitation n'est plus disponible.")
        if profil.email and normaliser_email(profil.email) != normaliser_email(invitation.email):
            raise ErreurMetier("L'adresse du dossier apprenant ne correspond plus à l'invitation.")
        if not profil.email:
            profil.email = invitation.email
            champs_a_enregistrer.append("email")
    elif invitation.role.nom == "Parent":
        if invitation.etablissement.type != TypeEtablissement.SCOLAIRE:
            raise ErreurMetier("Les rôles de parent sont réservés aux écoles classiques.")
        profil = invitation.responsable
        if profil is None or profil.etablissement_id != invitation.etablissement_id or profil.utilisateur_id:
            raise ErreurMetier("Le dossier du responsable associé à cette invitation n'est plus disponible.")
        if normaliser_email(profil.email) != normaliser_email(invitation.email):
            raise ErreurMetier("L'adresse du dossier du responsable ne correspond plus à l'invitation.")

    appartenance = Appartenance.sans_filtre.create(
        utilisateur=utilisateur, etablissement=invitation.etablissement, role=invitation.role
    )
    if profil is not None:
        profil.utilisateur = utilisateur
        profil.save(update_fields=champs_a_enregistrer)
    invitation.statut = Invitation.Statut.ACCEPTEE
    invitation.save(update_fields=["statut"])
    if not utilisateur.email_verifie:
        utilisateur.email_verifie = True
        utilisateur.save(update_fields=["email_verifie"])
    enregistrer_audit(invitation.etablissement, utilisateur, "invitation.acceptation", invitation)
    return appartenance


@sans_isolation
@transaction.atomic
def creer_compte_par_invitation(invitation, prenom, nom, mot_de_passe, username=None):
    utilisateur = inscrire_utilisateur(
        prenom, nom, invitation.email, mot_de_passe, email_verifie=True, username=username
    )
    accepter_invitation(invitation, utilisateur)
    return utilisateur