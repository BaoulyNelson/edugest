from django.urls import path

from . import views

app_name = "admissions"

urlpatterns = [
    path("", views.deposer, name="deposer"),
    path("dossiers/", views.liste, name="liste"),
    path("dossiers/<uuid:reference>/", views.detail, name="detail"),
    path("dossiers/<uuid:reference>/action/", views.action, name="action"),
]
