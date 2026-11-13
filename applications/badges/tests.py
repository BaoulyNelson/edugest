from unittest.mock import Mock

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from applications.apprenants.models import Inscription
from applications.noyau.outils_tests import inscrire, monde_scolaire

from .models import BadgeGenere
from .services import _dessiner_photo, _recadrer_photo, generer_badges


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
        self.assertIn(b"/Subtype /Image", contenu)
        badge = BadgeGenere.objects.get()
        self.assertEqual(badge.inscription, self.inscription)
        self.assertEqual(badge.type_badge, BadgeGenere.Type.APPRENANT)

    def test_pdf_badge_enseignant_utilise_le_modele_et_est_trace(self):
        contenu = generer_badges(
            self.monde["etab"],
            [(BadgeGenere.Type.ENSEIGNANT, self.monde["prof"])],
            self.monde["directeur"].utilisateur,
        )

        self.assertTrue(contenu.startswith(b"%PDF"))
        self.assertIn(b"/Subtype /Image", contenu)
        badge = BadgeGenere.objects.get()
        self.assertEqual(badge.appartenance, self.monde["prof"])
        self.assertEqual(badge.type_badge, BadgeGenere.Type.ENSEIGNANT)

    def test_photo_est_recadree_et_opaque_pour_couvrir_la_maquette(self):
        source = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        source.paste((230, 20, 20, 255), (0, 0, 50, 200))

        photo = _recadrer_photo(source, (40, 60))

        self.assertEqual(photo.size, (40, 60))
        self.assertEqual(photo.mode, "RGB")
        self.assertEqual(photo.getpixel((0, 30)), (230, 20, 20))
        self.assertEqual(photo.getpixel((39, 30)), (255, 255, 255))

    def test_badge_enseignant_sans_photo_affiche_ses_initiales(self):
        document = Mock()

        _dessiner_photo(
            document, 0, 0, {"photo": None, "nom": "Jean Paul"},
            BadgeGenere.Type.ENSEIGNANT,
        )

        self.assertEqual(document.drawCentredString.call_args.args[2], "JP")

    def test_page_badges_et_export_sont_proteges_et_disponibles(self):
        self.assertEqual(self.client.get(reverse("badges:liste")).status_code, 200)
        reponse = self.client.get(reverse("badges:classe_pdf", args=[self.monde["classe_a"].pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(Inscription.objects.filter(classe=self.monde["classe_a"]).exists())
