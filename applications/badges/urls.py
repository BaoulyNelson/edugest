from django.urls import path

from . import views

app_name = "badges"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("classes/<int:pk>.pdf", views.classe_pdf, name="classe_pdf"),
    path("enseignants.pdf", views.enseignants_pdf, name="enseignants_pdf"),
]
