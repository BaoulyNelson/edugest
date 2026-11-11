from django.urls import path

from . import views

app_name = "presences"

urlpatterns = [
    path("", views.appel, name="appel"),
    path("historique/", views.liste, name="liste"),
    path("mes-absences/", views.mes_absences, name="mes_absences"),
]
