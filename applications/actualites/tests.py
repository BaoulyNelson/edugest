from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from applications.noyau.outils_tests import monde_scolaire

from .models import Evenement, Publication


class TestsActualites(TestCase):
    def setUp(self):
        self.monde = monde_scolaire()

    def connecter(self, appartenance):
        self.client.force_login(appartenance.utilisateur)
        session = self.client.session
        session["etablissement_id"] = self.monde["etab"].pk
        session.save()

    def test_publication_publique_brouillon_et_publication_programmee(self):
        maintenant = timezone.now()
        Publication.objects.create(
            etablissement=self.monde["etab"], auteur=self.monde["directeur"].utilisateur,
            type=Publication.Type.ACTUALITE, titre="Information publiée", contenu="Visible",
            statut=Publication.Statut.PUBLIEE, publiee_le=maintenant - timedelta(hours=1),
        )
        Publication.objects.create(
            etablissement=self.monde["etab"], auteur=self.monde["directeur"].utilisateur,
            type=Publication.Type.ANNONCE, titre="Information brouillon", contenu="Privé",
            statut=Publication.Statut.BROUILLON, publiee_le=maintenant - timedelta(hours=1),
        )
        Publication.objects.create(
            etablissement=self.monde["etab"], auteur=self.monde["directeur"].utilisateur,
            type=Publication.Type.ANNONCE, titre="Information future", contenu="Pas encore visible",
            statut=Publication.Statut.PUBLIEE, publiee_le=maintenant + timedelta(days=1),
        )

        self.connecter(self.monde["prof"])
        reponse = self.client.get(reverse("actualites:liste"))

        self.assertContains(reponse, "Information publiée")
        self.assertNotContains(reponse, "Information brouillon")
        self.assertNotContains(reponse, "Information future")

        self.connecter(self.monde["directeur"])
        reponse = self.client.get(reverse("actualites:liste"))
        self.assertContains(reponse, "Information brouillon")
        self.assertContains(reponse, "Information future")

    def test_creer_et_archiver_une_publication_depuis_l_interface(self):
        self.connecter(self.monde["directeur"])
        reponse = self.client.post(reverse("actualites:publication_creer"), {
            "type": "ANNONCE",
            "titre": "Fermeture",
            "contenu": "L'établissement sera fermé vendredi.",
            "statut": "PUBLIEE",
            "publiee_le": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertRedirects(reponse, reverse("actualites:liste"), fetch_redirect_response=False)
        publication = Publication.objects.get(titre="Fermeture")

        reponse = self.client.post(reverse("actualites:publication_archiver", args=[publication.pk]))

        self.assertRedirects(reponse, reverse("actualites:liste"), fetch_redirect_response=False)
        publication.refresh_from_db()
        self.assertEqual(publication.statut, Publication.Statut.ARCHIVEE)

    def test_evenement_refuse_une_fin_anterieure_et_peut_etre_enregistre(self):
        self.connecter(self.monde["directeur"])
        maintenant = timezone.localtime()
        debut = (maintenant + timedelta(days=2)).replace(second=0, microsecond=0)
        fin = debut + timedelta(hours=2)
        reponse = self.client.post(reverse("actualites:evenement_creer"), {
            "titre": "Réunion",
            "description": "Réunion de rentrée.",
            "debut": fin.strftime("%Y-%m-%dT%H:%M"),
            "fin": debut.strftime("%Y-%m-%dT%H:%M"),
            "lieu": "Salle polyvalente",
            "statut": "PLANIFIE",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Evenement.objects.exists())

        reponse = self.client.post(reverse("actualites:evenement_creer"), {
            "titre": "Réunion",
            "description": "Réunion de rentrée.",
            "debut": debut.strftime("%Y-%m-%dT%H:%M"),
            "fin": fin.strftime("%Y-%m-%dT%H:%M"),
            "lieu": "Salle polyvalente",
            "statut": "PLANIFIE",
        })
        self.assertRedirects(reponse, reverse("actualites:liste"), fetch_redirect_response=False)
        self.assertEqual(Evenement.objects.get().titre, "Réunion")
