from django.urls import path

from . import views

app_name = "emploi_du_temps"

urlpatterns = [
    path("", views.gestion, name="gestion"),
    path("mon-emploi/", views.mon_emploi, name="mon_emploi"),
    path("creneau/nouveau/", views.creneau_creer, name="creneau_creer"),
    path("creneau/<int:pk>/supprimer/", views.creneau_supprimer, name="creneau_supprimer"),
    path("salles/", views.salles, name="salles"),
    path("salles/nouvelle/", views.salle_creer, name="salle_creer"),
]
