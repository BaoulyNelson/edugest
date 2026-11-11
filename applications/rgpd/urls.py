from django.urls import path

from . import views

app_name = "rgpd"

urlpatterns = [
    path("mes-donnees/", views.mes_donnees, name="mes_donnees"),
    path("export/<int:pk>/", views.exporter, name="exporter"),
    path("gestion/", views.demandes, name="demandes"),
    path("gestion/<int:pk>/traiter/", views.traiter, name="traiter"),
    path("apprenants/<int:pk>/consentements/", views.consentements, name="consentements"),
    path("apprenants/<int:pk>/anonymiser/", views.anonymiser, name="anonymiser"),
]
