from django.contrib.auth import views as vues_auth
from django.urls import path, reverse_lazy

from . import views


urlpatterns = [
    path("connexion/", views.VueConnexion.as_view(), name="connexion"),
    path("deconnexion/", vues_auth.LogoutView.as_view(), name="deconnexion"),
    path("inscription/", views.inscription_espace, name="inscription"),
    path("verification/renvoyer/", views.renvoyer_verification, name="renvoyer_verification"),
    path("verification/<str:jeton>/", views.verification_courriel, name="verification_courriel"),
    path("invitation/<str:jeton>/", views.invitation, name="invitation"),
    path("mot-de-passe/oublie/", vues_auth.PasswordResetView.as_view(
        template_name="comptes/mot_de_passe/oublie.html",
        email_template_name="comptes/courriels/reinitialisation.txt",
        subject_template_name="comptes/courriels/reinitialisation_sujet.txt",
        success_url=reverse_lazy("mot_de_passe_oublie_envoye"),
    ), name="mot_de_passe_oublie"),
    path("mot-de-passe/oublie/envoye/", vues_auth.PasswordResetDoneView.as_view(
        template_name="comptes/mot_de_passe/envoye.html",
    ), name="mot_de_passe_oublie_envoye"),
    path("mot-de-passe/reinitialiser/<uidb64>/<token>/", vues_auth.PasswordResetConfirmView.as_view(
        template_name="comptes/mot_de_passe/reinitialiser.html",
        success_url=reverse_lazy("mot_de_passe_reinitialise"),
    ), name="mot_de_passe_reinitialiser"),
    path("mot-de-passe/reinitialise/", vues_auth.PasswordResetCompleteView.as_view(
        template_name="comptes/mot_de_passe/reinitialise.html",
    ), name="mot_de_passe_reinitialise"),
    path("mot-de-passe/changer/", vues_auth.PasswordChangeView.as_view(
        template_name="comptes/mot_de_passe/changer.html",
        success_url=reverse_lazy("profil"),
    ), name="mot_de_passe_changer"),
    path("profil/", views.profil, name="profil"),
]