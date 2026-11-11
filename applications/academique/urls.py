from django.urls import path

from . import views

app_name = "academique"

urlpatterns = [
    path("annees/", views.annees, name="annees"),
    path("annees/nouvelle/", views.annee_creer, name="annee_creer"),
    path("annees/<int:pk>/", views.periodes, name="periodes"),
    path("annees/<int:pk>/action/", views.annee_action, name="annee_action"),
    path("annees/<int:pk>/periodes/nouvelle/", views.periode_creer, name="periode_creer"),
    path("periodes/<int:pk>/action/", views.periode_action, name="periode_action"),
    path("structure/", views.structure, name="structure"),
    path("niveaux/<int:pk>/modifier/", views.niveau_modifier, name="niveau_modifier"),
    path("classes/<int:pk>/modifier/", views.classe_modifier, name="classe_modifier"),
    path("presets/<int:pk>/appliquer/", views.appliquer_preset, name="appliquer_preset"),
]
