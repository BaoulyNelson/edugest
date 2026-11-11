from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from applications.academique.models import Classe
from applications.academique.services import annee_active
from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier
from . import services
from .forms import FormulaireMessage, FormulaireReponse
from .models import Conversation, NotificationMessage


def _classes_diffusables(request):
    annee = annee_active(request.etablissement)
    if annee is None:
        return Classe.objects.none()
    if a_la_permission(request, "messagerie.diffuser_tous"):
        return Classe.objects.filter(etablissement=request.etablissement, annee=annee)
    if a_la_permission(request, "messagerie.diffuser"):
        return services.classes_enseignant(request.etablissement, request.appartenance)
    return Classe.objects.none()


@permission_requise("messagerie.utiliser")
def boite(request):
    return render(request, "messagerie/boite.html", {
        "conversations": services.conversations_de(request.user),
    })


@permission_requise("messagerie.utiliser")
def nouveau(request):
    peut_diffuser = (
        a_la_permission(request, "messagerie.diffuser")
        or a_la_permission(request, "messagerie.diffuser_tous")
    )
    formulaire = FormulaireMessage(
        request.POST or None,
        utilisateur=request.user,
        etablissement=request.etablissement,
        appartenance=request.appartenance,
        peut_diffuser=peut_diffuser,
        classes=_classes_diffusables(request),
    )
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        destinataires = list(donnees.get("destinataires") or [])
        try:
            if donnees.get("classe"):
                conversations = services.diffuser(
                    request.user,
                    donnees["classe"],
                    donnees["sujet"],
                    donnees["texte"],
                    request.etablissement,
                    request.appartenance,
                    tout=a_la_permission(request, "messagerie.diffuser_tous"),
                    destinataires_supplementaires=destinataires,
                )
                messages.success(request, f"Message envoyé individuellement à {len(conversations)} personne(s).")
                return redirect("messagerie:boite")
            conversation = services.envoyer(
                request.user,
                destinataires,
                donnees["sujet"],
                donnees["texte"],
                request.etablissement,
                request.appartenance,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Message envoyé.")
            return redirect("messagerie:conversation", pk=conversation.pk)
    return render(request, "messagerie/nouveau.html", {"formulaire": formulaire})


@permission_requise("messagerie.utiliser")
def conversation(request, pk):
    objet = get_object_or_404(
        Conversation.objects.filter(participants__utilisateur=request.user).distinct(),
        pk=pk,
    )
    formulaire = FormulaireReponse(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.repondre(objet, request.user, formulaire.cleaned_data["texte"])
        except ErreurMetier as erreur:
            formulaire.add_error("texte", str(erreur))
        else:
            return redirect("messagerie:conversation", pk=pk)
    services.marquer_lu(objet, request.user)
    return render(request, "messagerie/conversation.html", {
        "conversation": objet,
        "messages_liste": objet.messages.select_related("auteur"),
        "participants": [
            participant.utilisateur
            for participant in objet.participants.select_related("utilisateur")
        ],
        "formulaire": formulaire,
    })


@permission_requise("messagerie.utiliser")
def notifications(request):
    return render(request, "messagerie/notifications.html", {
        "notifications": NotificationMessage.objects.filter(destinataire=request.user)[:50],
    })


@permission_requise("messagerie.utiliser")
@require_POST
def tout_marquer_lu(request):
    NotificationMessage.objects.filter(destinataire=request.user, lue=False).update(lue=True)
    return redirect("messagerie:notifications")


def compteur(request):
    if (
        getattr(request, "user", None) is None
        or not request.user.is_authenticated
        or getattr(request, "etablissement", None) is None
        or not a_la_permission(request, "messagerie.utiliser")
    ):
        return 0
    return services.nombre_notifications(request.user, request.etablissement)
