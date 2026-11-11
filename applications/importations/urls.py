from django.urls import path

from . import views

app_name = "importations"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/confirmer/", views.confirmer, name="confirmer"),
    path("<int:pk>/annuler/", views.annuler, name="annuler"),
]
