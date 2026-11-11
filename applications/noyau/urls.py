from django.urls import path

from applications.interface.ajout_rapide import ajout_rapide

from . import views

urlpatterns = [
    path("ajout-rapide/<str:cible>/", ajout_rapide, name="ajout_rapide"),
    path("langue/", views.choisir_langue, name="choisir_langue"),
    # Public
    path("", views.accueil_public, name="accueil_public"),
    # Application
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("etablissements/", views.etablissements, name="etablissements"),
    path("etablissements/choisir/", views.choisir_etablissement, name="choisir_etablissement_menu"),
    path("etablissements/<int:pk>/choisir/", views.choisir_etablissement, name="choisir_etablissement"),
    path("demarrage/", views.demarrage, name="demarrage"),
    path("parametres/", views.parametres, name="parametres"),
    path("abonnement/", views.abonnement, name="abonnement"),
    path("personnel/", views.personnel, name="personnel"),
    path("personnel/<int:pk>/action/", views.membre_action, name="membre_action"),
    path("personnel/invitations/<int:pk>/action/", views.invitation_action, name="invitation_action"),
    path("rapports/", views.rapports, name="rapports"),
    # Console de la plateforme
    path("plateforme/", views.plateforme, name="plateforme"),
    path("plateforme/configuration/", views.configuration_plateforme, name="configuration_plateforme"),
    path("plateforme/<int:pk>/action/", views.plateforme_action, name="plateforme_action"),
]
