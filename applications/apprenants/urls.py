from django.urls import path

from . import views

app_name = "apprenants"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("nouveau/", views.creer, name="creer"),
    path("<int:pk>/modifier/", views.modifier, name="modifier"),
    path("<int:pk>/", views.detail, name="detail"),
    path("inscriptions/", views.inscriptions, name="inscriptions"),
    path("inscriptions/valider-lot/", views.inscriptions_valider_lot, name="inscriptions_valider_lot"),
    path("inscriptions/nouvelle/", views.inscription_creer, name="inscription_creer"),
    path("inscriptions/<int:pk>/modifier/", views.inscription_modifier, name="inscription_modifier"),
    path("inscriptions/<int:pk>/", views.inscription_detail, name="inscription_detail"),
    path("inscriptions/<int:pk>/action/", views.inscription_action, name="inscription_action"),
]
