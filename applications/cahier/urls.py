from django.urls import path

from . import views

app_name = "cahier"

urlpatterns = [
    path("", views.mon_cahier, name="mon_cahier"),
    path("seances/", views.entrees, name="entrees"),
    path("seances/nouvelle/", views.entree_creer, name="entree_creer"),
    path("devoirs/", views.devoirs, name="devoirs"),
    path("devoirs/nouveau/", views.devoir_creer, name="devoir_creer"),
    path("devoirs/<int:pk>/", views.devoir_detail, name="devoir"),
    path("remises/<int:pk>/apprecier/", views.apprecier, name="apprecier"),
    path("remises/<int:pk>/corriger/", views.remise_correction, name="remise_correction"),
    path("fichier/<str:type_objet>/<int:pk>/", views.telecharger, name="telecharger"),
]
