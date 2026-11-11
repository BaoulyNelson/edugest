from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.noyau.models import ModeleEtablissement


class Conversation(ModeleEtablissement):
    sujet = models.CharField("sujet", max_length=150)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
    )
    date_creation = models.DateTimeField(default=timezone.now)
    derniere_activite = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "conversation"
        verbose_name_plural = "conversations"
        ordering = ["-derniere_activite"]

    def __str__(self):
        return self.sujet


class Participant(ModeleEtablissement):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participations_messagerie",
    )
    dernier_lu = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "participant"
        verbose_name_plural = "participants"
        constraints = [
            models.UniqueConstraint(fields=["conversation", "utilisateur"], name="participant_conversation_unique"),
        ]


class Message(ModeleEtablissement):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
    )
    texte = models.TextField("message")
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ["date", "pk"]


class NotificationMessage(ModeleEtablissement):
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications_messagerie",
    )
    titre = models.CharField(max_length=150)
    texte = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=200)
    lue = models.BooleanField(default=False)
    date = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "notification de messagerie"
        verbose_name_plural = "notifications de messagerie"
        ordering = ["-date", "-pk"]
