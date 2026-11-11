from django.urls import path

from . import views

app_name = "pedagogie"

urlpatterns = [
    path("matieres/", views.matieres, name="matieres"),
    path("niveaux/<int:pk>/", views.niveau, name="niveau"),
    path("affectations/", views.affectations, name="affectations"),
    path("affectations/inviter-enseignant/", views.inviter_enseignant, name="inviter_enseignant"),
    path("ressources/", views.ressources, name="ressources"),
    path("ressources/<int:pk>/fichier/", views.telecharger_ressource, name="telecharger_ressource"),
    path("quiz/<int:pk>/", views.quiz_detail, name="quiz_detail"),
]
