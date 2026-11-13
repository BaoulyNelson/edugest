from django.urls import path

from . import views

app_name = "actualites"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("publications/nouvelle/", views.publication_creer, name="publication_creer"),
    path("publications/<int:pk>/modifier/", views.publication_modifier, name="publication_modifier"),
    path("publications/<int:pk>/archiver/", views.publication_archiver, name="publication_archiver"),
    path("evenements/nouveau/", views.evenement_creer, name="evenement_creer"),
    path("evenements/<int:pk>/modifier/", views.evenement_modifier, name="evenement_modifier"),
]
