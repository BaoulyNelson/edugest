from django.urls import path

from . import views

app_name = "finances"

urlpatterns = [
    path("factures/", views.factures, name="factures"),
    path("factures/<int:pk>/", views.facture_detail, name="facture_detail"),
    path("factures/<int:pk>/encaisser/", views.facture_encaisser, name="facture_encaisser"),
    path("factures/<int:pk>/annuler/", views.facture_annuler, name="facture_annuler"),
    path("factures/mes-factures/", views.mes_factures, name="mes_factures"),
    path("recu/<int:pk>/", views.recu, name="recu"),
    path("tarifs/", views.tarifs, name="tarifs"),
    path("paiements/", views.paiements, name="paiements"),
    path("paiements/nouveau/", views.paiement_creer, name="paiement_creer"),
    path("paiements/<int:pk>/rembourser/", views.paiement_rembourser, name="paiement_rembourser"),
    path("depenses/", views.depenses, name="depenses"),
    path("depenses/nouvelle/", views.depense_creer, name="depense_creer"),
    path("rapports/", views.rapports, name="rapports"),
]
