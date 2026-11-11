from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from applications.academique.models import Classe
from applications.academique.services import annee_active
from applications.apprenants.models import Apprenant, Inscription, LienResponsable
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance
from applications.noyau.services import enregistrer_audit
from applications.pedagogie.models import AffectationEnseignant

from .models import Conversation, Message, NotificationMessage, Participant


ROLES_DIRECTION = {
    "Administrateur de l'établissement",
    "Directeur",
    "Secrétaire",
    "Responsable pédagogique",
}


def classes_enseignant(etablissement, appartenance):
    annee = annee_active(etablissement)
    if annee is None or appartenance is None:
        return Classe.objects.none()
    affectations = AffectationEnseignant.objects.filter(
        etablissement=etablissement,
        appartenance=appartenance,
        matiere_niveau__annee=annee,
    )
    directes = affectations.filter(classe__isnull=False).values_list("classe_id", flat=True)
    niveaux = affectations.filter(classe__isnull=True).values_list("matiere_niveau__niveau_id", flat=True)
    return Classe.objects.filter(annee=annee).filter(
        Q(pk__in=directes) | Q(niveau_id__in=niveaux),
    ).distinct()


def utilisateurs_famille_de_classes(etablissement, classes_ids):
    apprenants = Inscription.objects.filter(
        etablissement=etablissement,
        classe_id__in=classes_ids,
        statut=Inscription.Statut.VALIDEE,
        annee__statut="ACTIVE",
    ).values_list("apprenant_id", flat=True)
    comptes = set(
        Apprenant.objects.filter(
            etablissement=etablissement, pk__in=apprenants, utilisateur__isnull=False,
        ).values_list("utilisateur_id", flat=True)
    )
    comptes.update(
        LienResponsable.objects.filter(
            etablissement=etablissement,
            apprenant_id__in=apprenants,
            responsable__utilisateur__isnull=False,
        ).values_list("responsable__utilisateur_id", flat=True)
    )
    return comptes


def parents_de_la_classe(etablissement, classe):
    return utilisateurs_famille_de_classes(etablissement, [classe.pk])


def _famille_inscriptions(utilisateur, etablissement):
    return Inscription.objects.filter(
        etablissement=etablissement,
        statut=Inscription.Statut.VALIDEE,
        annee__statut="ACTIVE",
        classe__isnull=False,
    ).filter(
        Q(apprenant__utilisateur=utilisateur)
        | Q(apprenant__liens_responsables__responsable__utilisateur=utilisateur)
    ).distinct()


def identifiants_autorises(utilisateur, etablissement, appartenance):
    tous = set(
        Appartenance.sans_filtre.filter(
            etablissement=etablissement, actif=True,
        ).values_list("utilisateur_id", flat=True)
    )
    if appartenance is None:
        autorises = set()
    else:
        role = appartenance.role.nom
        direction = set(
            Appartenance.sans_filtre.filter(
                etablissement=etablissement,
                actif=True,
                role__nom__in=ROLES_DIRECTION,
            ).values_list("utilisateur_id", flat=True)
        )
        if role in ROLES_DIRECTION:
            autorises = tous
        elif role == "Enseignant":
            classes = list(classes_enseignant(etablissement, appartenance).values_list("pk", flat=True))
            autorises = direction | utilisateurs_famille_de_classes(etablissement, classes)
        elif role in {"Parent", "Apprenant"}:
            inscriptions = _famille_inscriptions(utilisateur, etablissement)
            classes = set(inscriptions.values_list("classe_id", flat=True))
            classes_qs = Classe.objects.filter(etablissement=etablissement, pk__in=classes)
            annee = annee_active(etablissement)
            affectations = AffectationEnseignant.objects.filter(
                etablissement=etablissement,
                matiere_niveau__annee=annee,
            ).filter(Q(classe_id__in=classes) | Q(classe__isnull=True, matiere_niveau__niveau_id__in=classes_qs.values("niveau_id")))
            autorises = direction | set(affectations.values_list("appartenance__utilisateur_id", flat=True))
        elif role == "Comptable":
            autorises = direction | set(
                Appartenance.sans_filtre.filter(
                    etablissement=etablissement, actif=True,
                    role__nom__in=("Parent", "Apprenant"),
                ).values_list("utilisateur_id", flat=True)
            )
        else:
            autorises = direction
    autorises.discard(utilisateur.pk)
    return autorises


def destinataires_autorises(utilisateur, etablissement, appartenance):
    ids = identifiants_autorises(utilisateur, etablissement, appartenance)
    from applications.noyau.models import Utilisateur

    return Utilisateur.objects.filter(
        pk__in=Appartenance.sans_filtre.filter(
            etablissement=etablissement, actif=True, utilisateur_id__in=ids,
        ).values("utilisateur_id"),
    ).order_by("last_name", "first_name")


def notifier(etablissement, utilisateur, titre, texte="", url=""):
    return NotificationMessage.objects.create(
        etablissement=etablissement,
        destinataire=utilisateur,
        titre=titre[:150],
        texte=texte[:300],
        url=url,
    )


@transaction.atomic
def envoyer(auteur, destinataires, sujet, texte, etablissement, appartenance):
    destinataires = list({destinataire.pk: destinataire for destinataire in destinataires}.values())
    if not destinataires:
        raise ErreurMetier("Choisissez au moins un destinataire.")
    if not (texte or "").strip():
        raise ErreurMetier("Le message est vide.")
    autorises = identifiants_autorises(auteur, etablissement, appartenance)
    interdits = [
        destinataire
        for destinataire in destinataires
        if destinataire.pk not in autorises
        or not Appartenance.sans_filtre.filter(
            utilisateur=destinataire, etablissement=etablissement, actif=True,
        ).exists()
    ]
    if interdits:
        raise ErreurMetier(
            "Vous ne pouvez pas écrire à : "
            + ", ".join(destinataire.nom_affiche for destinataire in interdits)
            + "."
        )
    conversation = Conversation.objects.create(
        etablissement=etablissement,
        sujet=(sujet or "").strip() or "(sans sujet)",
        cree_par=auteur,
    )
    maintenant = timezone.now()
    Participant.objects.create(
        etablissement=etablissement,
        conversation=conversation,
        utilisateur=auteur,
        dernier_lu=maintenant,
    )
    for destinataire in destinataires:
        Participant.objects.create(
            etablissement=etablissement,
            conversation=conversation,
            utilisateur=destinataire,
        )
        notifier(
            etablissement, destinataire, f"Message de {auteur.nom_affiche}",
            conversation.sujet, f"/messagerie/{conversation.pk}/",
        )
    Message.objects.create(
        etablissement=etablissement,
        conversation=conversation,
        auteur=auteur,
        texte=texte.strip(),
    )
    enregistrer_audit(
        etablissement, auteur, "messagerie.conversation", conversation,
        apres={"participants": len(destinataires) + 1},
    )
    return conversation


@transaction.atomic
def diffuser(
    auteur, classe, sujet, texte, etablissement, appartenance, tout=False,
    destinataires_supplementaires=(),
):
    if not (tout or classes_enseignant(etablissement, appartenance).filter(pk=classe.pk).exists()):
        raise ErreurMetier("Vous ne pouvez pas diffuser un message à cette classe.")
    destinataires = utilisateurs_famille_de_classes(etablissement, [classe.pk])
    destinataires.update(
        destinataire.pk for destinataire in destinataires_supplementaires
    )
    from applications.noyau.models import Utilisateur

    utilisateurs = list(Utilisateur.objects.filter(pk__in=destinataires))
    if not utilisateurs:
        raise ErreurMetier("Aucun élève ou responsable actif dans cette classe.")
    return [
        envoyer(
            auteur, [utilisateur], sujet, texte, etablissement, appartenance,
        )
        for utilisateur in utilisateurs
    ]


@transaction.atomic
def repondre(conversation, auteur, texte):
    participant = Participant.objects.filter(
        conversation=conversation, utilisateur=auteur,
    ).first()
    if participant is None:
        raise ErreurMetier("Vous ne participez pas à cette conversation.")
    if not (texte or "").strip():
        raise ErreurMetier("Le message est vide.")
    message = Message.objects.create(
        etablissement=conversation.etablissement,
        conversation=conversation,
        auteur=auteur,
        texte=texte.strip(),
    )
    conversation.derniere_activite = message.date
    conversation.save(update_fields=["derniere_activite"])
    participant.dernier_lu = message.date
    participant.save(update_fields=["dernier_lu"])
    for destinataire in conversation.participants.exclude(utilisateur=auteur).select_related("utilisateur"):
        notifier(
            conversation.etablissement,
            destinataire.utilisateur,
            f"Réponse de {auteur.nom_affiche}",
            conversation.sujet,
            f"/messagerie/{conversation.pk}/",
        )
    return message


def marquer_lu(conversation, utilisateur):
    maintenant = timezone.now()
    Participant.objects.filter(
        conversation=conversation, utilisateur=utilisateur,
    ).update(dernier_lu=maintenant)
    NotificationMessage.objects.filter(
        destinataire=utilisateur, url=f"/messagerie/{conversation.pk}/", lue=False,
    ).update(lue=True)


def conversations_de(utilisateur):
    conversations = []
    participations = Participant.objects.filter(
        utilisateur=utilisateur,
    ).select_related("conversation").prefetch_related("conversation__participants__utilisateur")
    for participation in participations:
        conversation = participation.conversation
        dernier = conversation.messages.select_related("auteur").order_by("-date", "-pk").first()
        non_lu = bool(
            dernier
            and dernier.auteur_id != utilisateur.pk
            and (participation.dernier_lu is None or dernier.date > participation.dernier_lu)
        )
        personnes = [
            participant.utilisateur.nom_affiche
            for participant in conversation.participants.all()
            if participant.utilisateur_id != utilisateur.pk
        ]
        conversations.append({
            "conversation": conversation,
            "dernier": dernier,
            "non_lu": non_lu,
            "personnes": personnes,
        })
    return sorted(conversations, key=lambda ligne: ligne["conversation"].derniere_activite, reverse=True)


def nombre_notifications(utilisateur, etablissement):
    return NotificationMessage.objects.filter(
        etablissement=etablissement, destinataire=utilisateur, lue=False,
    ).count()
