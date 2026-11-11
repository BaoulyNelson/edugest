"""Services SaaS : espaces, abonnements et gestion des invitations d'établissement.

Les services de compte (inscription, vérification et acceptation) sont dans ``applications.comptes.services``.
"""
import secrets
import smtplib
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .contexte import sans_isolation
from .exceptions import ErreurMetier
from .models import (
    Abonnement, Appartenance, Etablissement, EvenementPaiement, Invitation, Plan, Role,
    TypeEtablissement, UsageAbonnement,
)
from .services import creer_etablissement, enregistrer_audit, nom_plateforme

ROLE_ADMINISTRATEUR = "Administrateur de l'établissement"
DUREE_ESSAI_JOURS = 30
DUREE_INVITATION_JOURS = 7

PLANS_PAR_DEFAUT = {
    "ESSAI": ("Essai gratuit", 100, 10, 0),
    "STANDARD": ("Standard", 1000, 50, 49),
    "PREMIUM": ("Premium", None, None, 149),
}


def obtenir_plan(code):
    if code not in PLANS_PAR_DEFAUT:
        plan = Plan.objects.filter(code=code).first()
        if plan is None:
            raise ErreurMetier("La formule sélectionnée n'existe pas.")
        return plan
    nom, limite_apprenants, limite_membres, prix = PLANS_PAR_DEFAUT[code]
    plan, _ = Plan.objects.get_or_create(
        code=code, defaults={"nom": nom, "limite_apprenants": limite_apprenants,
                             "limite_membres": limite_membres, "prix_mensuel": prix},
    )
    return plan


def ouvrir_abonnement_essai(etablissement, code_plan="ESSAI"):
    return Abonnement.objects.create(
        etablissement=etablissement, plan=obtenir_plan(code_plan), statut=Abonnement.Statut.ESSAI,
        date_fin_essai=timezone.localdate() + timedelta(days=DUREE_ESSAI_JOURS),
    )


def etat_abonnement(etablissement):
    """Renvoie (actif, message). Un établissement suspendu ou dont l'essai est terminé est bloqué."""
    abonnement = Abonnement.objects.filter(etablissement=etablissement).select_related("plan").first()
    if abonnement is None:
        return True, ""
    if abonnement.statut == Abonnement.Statut.ACTIF:
        return True, ""
    if abonnement.statut == Abonnement.Statut.ESSAI:
        if abonnement.date_fin_essai and abonnement.date_fin_essai < timezone.localdate():
            return False, "La période d'essai gratuite est terminée."
        return True, ""
    if abonnement.statut == Abonnement.Statut.SUSPENDU:
        return False, "L'abonnement de cet établissement est suspendu."
    return False, "L'abonnement de cet établissement est résilié."


def usage_abonnement(etablissement):
    from applications.apprenants.models import Apprenant

    abonnement = Abonnement.objects.filter(etablissement=etablissement).select_related("plan").first()
    apprenants = Apprenant.sans_filtre.filter(etablissement=etablissement, actif=True).count()
    membres = Appartenance.sans_filtre.filter(etablissement=etablissement, actif=True).count()
    en_attente = Invitation.sans_filtre.filter(
        etablissement=etablissement, statut=Invitation.Statut.EN_ATTENTE, date_expiration__gt=timezone.now()
    ).count()
    return {"abonnement": abonnement, "apprenants": apprenants, "membres": membres, "invitations": en_attente}


def verifier_quota(etablissement, ressource, ajout=1):
    """Refuse un ajout qui dépasserait la limite du plan (ressource : 'apprenants' ou 'membres')."""
    usage = usage_abonnement(etablissement)
    abonnement = usage["abonnement"]
    if abonnement is None:
        return
    limite = getattr(abonnement.plan, f"limite_{ressource}")
    courant = usage[ressource] + (usage["invitations"] if ressource == "membres" else 0)
    if limite is not None and courant + ajout > limite:
        nom = "apprenants" if ressource == "apprenants" else "membres du personnel"
        raise ErreurMetier(
            f"La limite du plan « {abonnement.plan} » est atteinte ({limite} {nom}). "
            "Passez à une formule supérieure pour en ajouter."
        )


@transaction.atomic
def enregistrer_evenement_paiement(etablissement, fournisseur, identifiant_externe, type_evenement, donnees=None):
    """Enregistre un événement idempotent après validation de signature par l'adaptateur fournisseur."""
    abonnement = Abonnement.objects.filter(etablissement=etablissement).first()
    if abonnement is None:
        raise ErreurMetier("Aucun abonnement n'est associé à cet établissement.")
    if not fournisseur.strip() or not identifiant_externe.strip():
        raise ErreurMetier("Le fournisseur et l'identifiant externe sont obligatoires.")
    if type_evenement not in dict(EvenementPaiement.Type.choices):
        raise ErreurMetier("Type d'événement de paiement invalide.")
    champs_autorises = {"reference", "montant", "devise", "statut"}
    details = {
        cle: str(valeur)[:150]
        for cle, valeur in (donnees or {}).items()
        if cle in champs_autorises and valeur is not None
    }
    evenement, cree = EvenementPaiement.objects.get_or_create(
        etablissement=etablissement,
        fournisseur=fournisseur.strip()[:40],
        identifiant_externe=identifiant_externe.strip()[:150],
        defaults={
            "abonnement": abonnement,
            "type_evenement": type_evenement,
            "donnees": details,
        },
    )
    return evenement, cree


@transaction.atomic
def enregistrer_usage_abonnement(etablissement, date_mesure=None):
    """Capture une photo quotidienne des quotas d'un établissement."""
    date_mesure = date_mesure or timezone.localdate()
    from applications.apprenants.models import Apprenant

    apprenants = Apprenant.sans_filtre.filter(etablissement=etablissement, actif=True).count()
    membres = Appartenance.sans_filtre.filter(etablissement=etablissement, actif=True).count()
    invitations = Invitation.sans_filtre.filter(
        etablissement=etablissement, statut=Invitation.Statut.EN_ATTENTE,
        date_expiration__gt=timezone.now(),
    ).count()
    mesure, _ = UsageAbonnement.objects.update_or_create(
        etablissement=etablissement, date=date_mesure,
        defaults={
            "nombre_apprenants": apprenants,
            "nombre_membres": membres,
            "invitations_en_attente": invitations,
        },
    )
    return mesure


# ----------------------------------------------------------------------------- e-mails


def envoyer_courriel(destinataire, sujet, texte):
    try:
        nombre_envoye = send_mail(
            sujet, texte, settings.DEFAULT_FROM_EMAIL, [destinataire], fail_silently=False
        )
    except (smtplib.SMTPException, OSError) as erreur:
        raise ErreurMetier(
            "L'e-mail n'a pas pu être envoyé. Vérifiez la configuration SMTP puis réessayez."
        ) from erreur
    if nombre_envoye != 1:
        raise ErreurMetier("Le serveur de courriel n'a pas confirmé l'envoi du message.")
    return nombre_envoye


def courriel_en_mode_console():
    """Le backend console affiche les e-mails dans le terminal, sans les livrer."""
    return settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


def envoyer_verification(utilisateur, url_base):
    from applications.comptes.services import envoyer_verification as envoyer

    return envoyer(utilisateur, url_base)


def verifier_courriel(jeton):
    from applications.comptes.services import verifier_courriel as verifier

    return verifier(jeton)


# ----------------------------------------------------------------------------- comptes et espaces


def normaliser_email(email):
    from applications.comptes.services import normaliser_email as normaliser

    return normaliser(email)


def inscrire_utilisateur(prenom, nom, email, mot_de_passe, url_base=None, email_verifie=False, username=None):
    from applications.comptes.services import inscrire_utilisateur as inscrire

    return inscrire(
        prenom, nom, email, mot_de_passe, url_base=url_base,
        email_verifie=email_verifie, username=username,
    )


def jeton_verification(utilisateur):
    from applications.comptes.services import jeton_verification as creer_jeton

    return creer_jeton(utilisateur)


@sans_isolation
@transaction.atomic
def creer_espace(utilisateur, nom_etablissement, type_etablissement, par=None, code_plan="ESSAI"):
    """Crée un établissement (tenant) dont l'utilisateur devient l'administrateur. Essai gratuit inclus."""
    etablissement = creer_etablissement(
        nom_etablissement.strip(), TypeEtablissement(type_etablissement), code_plan=code_plan
    )
    role = Role.sans_filtre.get(etablissement=etablissement, nom=ROLE_ADMINISTRATEUR)
    Appartenance.sans_filtre.create(utilisateur=utilisateur, etablissement=etablissement, role=role)
    enregistrer_audit(etablissement, par or utilisateur, "espace.creation", etablissement)
    return etablissement


# ----------------------------------------------------------------------------- invitations


@transaction.atomic
def inviter(etablissement, email, role, par, url_base, apprenant=None, responsable=None):
    email = normaliser_email(email)
    if role.etablissement_id != etablissement.pk:
        raise ErreurMetier("Ce rôle n'appartient pas à cet établissement.")
    if role.nom == "Parent" and etablissement.type != TypeEtablissement.SCOLAIRE:
        raise ErreurMetier("Les rôles de parent sont réservés aux écoles classiques.")
    if role.nom == "Apprenant":
        if apprenant is None or responsable is not None:
            raise ErreurMetier("Sélectionnez un dossier apprenant pour cette invitation.")
        if apprenant.etablissement_id != etablissement.pk or apprenant.utilisateur_id:
            raise ErreurMetier("Le dossier apprenant est invalide ou déjà associé à un compte.")
        if apprenant.email and normaliser_email(apprenant.email) != email:
            raise ErreurMetier("L'adresse invitée doit correspondre à celle du dossier apprenant.")
    elif role.nom == "Parent":
        if responsable is None or apprenant is not None:
            raise ErreurMetier("Sélectionnez un dossier de responsable pour cette invitation.")
        if responsable.etablissement_id != etablissement.pk or responsable.utilisateur_id:
            raise ErreurMetier("Le dossier du responsable est invalide ou déjà associé à un compte.")
        if normaliser_email(responsable.email) != email:
            raise ErreurMetier("L'adresse invitée doit correspondre à celle du dossier du responsable.")
    elif apprenant is not None or responsable is not None:
        raise ErreurMetier("Les dossiers ne peuvent être liés qu'aux rôles Apprenant et Parent.")
    if Appartenance.sans_filtre.filter(etablissement=etablissement, utilisateur__email__iexact=email, actif=True).exists():
        raise ErreurMetier("Cette personne fait déjà partie de l'établissement.")
    if Invitation.sans_filtre.filter(
        etablissement=etablissement, email__iexact=email, statut=Invitation.Statut.EN_ATTENTE,
        date_expiration__gt=timezone.now(),
    ).exists():
        raise ErreurMetier("Une invitation est déjà en attente pour cette adresse. Renvoyez-la ou révoquez-la.")
    verifier_quota(etablissement, "membres")
    invitation = Invitation.sans_filtre.create(
        etablissement=etablissement, email=email, role=role, jeton=secrets.token_urlsafe(32),
        apprenant=apprenant, responsable=responsable,
        invitee_par=par, date_expiration=timezone.now() + timedelta(days=DUREE_INVITATION_JOURS),
    )
    envoyer_invitation(invitation, url_base)
    enregistrer_audit(etablissement, par, "invitation.envoi", invitation, apres={"email": email, "role": role.nom})
    return invitation


def envoyer_invitation(invitation, url_base):
    lien = f"{url_base}/invitation/{invitation.jeton}/"
    auteur = invitation.invitee_par.nom_affiche if invitation.invitee_par else "Un administrateur"
    envoyer_courriel(
        invitation.email, f"Invitation à rejoindre {invitation.etablissement.nom} sur {nom_plateforme()}",
        f"{auteur} vous invite à rejoindre « {invitation.etablissement.nom} » avec le rôle {invitation.role.nom}.\n\n"
        f"Acceptez l'invitation et créez votre compte ici :\n{lien}\n\nCe lien expire le "
        f"{invitation.date_expiration:%d/%m/%Y}.",
    )


@transaction.atomic
@transaction.atomic
def renvoyer_invitation(invitation, url_base):
    if invitation.statut != Invitation.Statut.EN_ATTENTE:
        raise ErreurMetier("Seule une invitation en attente peut être renvoyée.")
    invitation.date_expiration = timezone.now() + timedelta(days=DUREE_INVITATION_JOURS)
    invitation.save(update_fields=["date_expiration"])
    envoyer_invitation(invitation, url_base)
    return invitation


def revoquer_invitation(invitation, par=None):
    if invitation.statut != Invitation.Statut.EN_ATTENTE:
        raise ErreurMetier("Cette invitation n'est plus en attente.")
    invitation.statut = Invitation.Statut.REVOQUEE
    invitation.save(update_fields=["statut"])
    enregistrer_audit(invitation.etablissement, par, "invitation.revocation", invitation)
    return invitation


def invitation_par_jeton(jeton):
    from applications.comptes.services import invitation_par_jeton as trouver

    return trouver(jeton)


@sans_isolation
@transaction.atomic
def accepter_invitation(invitation, utilisateur):
    from applications.comptes.services import accepter_invitation as accepter

    return accepter(invitation, utilisateur)


@sans_isolation
@transaction.atomic
def creer_compte_par_invitation(invitation, prenom, nom, mot_de_passe, username=None):
    from applications.comptes.services import creer_compte_par_invitation as creer

    return creer(invitation, prenom, nom, mot_de_passe, username=username)


# ----------------------------------------------------------------------------- gestion des membres


@transaction.atomic
def changer_role_membre(appartenance, role, par):
    if role.etablissement_id != appartenance.etablissement_id:
        raise ErreurMetier("Ce rôle n'appartient pas à cet établissement.")
    if role.nom == "Parent" and appartenance.etablissement.type != TypeEtablissement.SCOLAIRE:
        raise ErreurMetier("Les rôles de parent sont réservés aux écoles classiques.")
    _proteger_dernier_administrateur(appartenance, role)
    ancien = appartenance.role.nom
    appartenance.role = role
    appartenance.save(update_fields=["role"])
    enregistrer_audit(appartenance.etablissement, par, "membre.role", appartenance, avant={"role": ancien}, apres={"role": role.nom})
    return appartenance


@transaction.atomic
def basculer_membre(appartenance, actif, par):
    if not actif:
        _proteger_dernier_administrateur(appartenance, None)
    if actif:
        verifier_quota(appartenance.etablissement, "membres")
    appartenance.actif = actif
    appartenance.save(update_fields=["actif"])
    enregistrer_audit(appartenance.etablissement, par, "membre.activation" if actif else "membre.desactivation", appartenance)
    return appartenance


def _proteger_dernier_administrateur(appartenance, nouveau_role):
    """Un établissement doit toujours conserver au moins un administrateur actif."""
    if appartenance.role.nom != ROLE_ADMINISTRATEUR:
        return
    if nouveau_role is not None and nouveau_role.nom == ROLE_ADMINISTRATEUR:
        return
    autres = Appartenance.sans_filtre.filter(
        etablissement=appartenance.etablissement, actif=True, role__nom=ROLE_ADMINISTRATEUR
    ).exclude(pk=appartenance.pk)
    if not autres.exists():
        raise ErreurMetier("Impossible : l'établissement doit conserver au moins un administrateur actif.")


# ----------------------------------------------------------------------------- console de la plateforme


@sans_isolation
@transaction.atomic
def modifier_abonnement(etablissement, statut=None, code_plan=None, par=None):
    abonnement = Abonnement.objects.get(etablissement=etablissement)
    statuts_valides = {choix for choix, _ in Abonnement.Statut.choices}
    if statut is not None and statut not in statuts_valides:
        raise ErreurMetier("Le statut d'abonnement sélectionné est invalide.")
    if code_plan and code_plan not in PLANS_PAR_DEFAUT and not Plan.objects.filter(code=code_plan).exists():
        raise ErreurMetier("La formule sélectionnée n'existe pas.")
    avant = {"statut": abonnement.statut, "plan": abonnement.plan.code}
    if code_plan:
        abonnement.plan = obtenir_plan(code_plan)
    if statut:
        abonnement.statut = statut
        if statut == Abonnement.Statut.ACTIF:
            abonnement.date_fin_essai = None
    abonnement.save()
    enregistrer_audit(etablissement, par, "abonnement.modification", abonnement, avant=avant,
                      apres={"statut": abonnement.statut, "plan": abonnement.plan.code})
    return abonnement


@sans_isolation
@transaction.atomic
def modifier_etat_etablissement(etablissement, actif, par=None):
    if not isinstance(actif, bool):
        raise ErreurMetier("L'état de l'établissement est invalide.")
    avant = {"actif": etablissement.actif}
    if avant["actif"] == actif:
        return etablissement
    etablissement.actif = actif
    etablissement.save(update_fields=["actif"])
    enregistrer_audit(
        etablissement, par, "espace.activation" if actif else "espace.suspension",
        etablissement, avant=avant, apres={"actif": actif},
    )
    return etablissement
