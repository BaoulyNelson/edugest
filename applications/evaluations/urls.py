from django.urls import path

from . import views

app_name = "evaluations"

urlpatterns = [
    path("mes-evaluations/", views.mes_evaluations, name="mes_evaluations"),
    path("classes/", views.classes, name="classes"),
    path("configuration/<int:affectation_pk>/<int:periode_pk>/", views.configuration, name="configuration"),
    path("saisie/<int:pk>/", views.saisie, name="saisie"),
    path("synthese/<int:pk>/", views.synthese, name="synthese"),
    path("resultats/", views.resultats, name="resultats"),
    path("mes-resultats/", views.portail, name="portail"),
    path(
        "resultats/document/<int:inscription_pk>/<int:periode_pk>/creer/",
        views.creer_document_resultat, name="document_creer",
    ),
    path(
        "resultats/document/<int:pk>/revoquer/",
        views.revoquer_document_resultat, name="document_revoquer",
    ),
    path(
        "resultats/document/<int:pk>/telecharger/",
        views.telecharger_document_resultat, name="document_telecharger",
    ),
]
