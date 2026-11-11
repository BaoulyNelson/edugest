from django.urls import path

from . import views

app_name = "messagerie"

urlpatterns = [
    path("", views.boite, name="boite"),
    path("nouveau/", views.nouveau, name="nouveau"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/lues/", views.tout_marquer_lu, name="tout_lu"),
    path("<int:pk>/", views.conversation, name="conversation"),
]
