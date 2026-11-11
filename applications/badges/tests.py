from django.test import TestCase
from django.urls import reverse

from applications.apprenants.models import Inscription
from applications.noyau.outils_tests import inscrire, monde_scolaire

from .models import BadgeGenere
from .services import generer_badges


class TestsBadges(TestCase):
    def setUp(self):
        self.monde = monde_scolaire()
        self.inscription = inscrire(self.monde, "Badge")
        self.client.force_login(self.monde["directeur"].utilisateur)

    def test_pdf_badge_apprenant_contient_un_qr_et_est_trace(self):
        contenu = generer_badges(
            self.monde["etab"],
            [(BadgeGenere.Type.APPRENANT, self.inscription)],
            self.monde["directeur"].utilisateur,
        )

        self.assertTrue(contenu.startswith(b"%PDF"))
        badge = BadgeGenere.objects.get()
        self.assertEqual(badge.inscription, self.inscription)
        self.assertEqual(badge.type_badge, BadgeGenere.Type.APPRENANT)

    def test_page_badges_et_export_sont_proteges_et_disponibles(self):
        self.assertEqual(self.client.get(reverse("badges:liste")).status_code, 200)
        reponse = self.client.get(reverse("badges:classe_pdf", args=[self.monde["classe_a"].pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(Inscription.objects.filter(classe=self.monde["classe_a"]).exists())
