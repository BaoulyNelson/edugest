from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from applications.noyau.models import Appartenance, Role, TypeEtablissement, Utilisateur
from applications.noyau.services import creer_etablissement

from .models import TentativeConnexion


class TestsLimitationConnexion(TestCase):
    def setUp(self):
        self.utilisateur = Utilisateur.objects.create_user(
            "limite", "limite@example.test", "MotDePasse!Fort2026"
        )

    def tenter(self, mot_de_passe):
        return self.client.post(reverse("connexion"), {
            "username": self.utilisateur.username,
            "password": mot_de_passe,
        })

    def test_sixieme_tentative_est_bloquee_apres_cinq_echecs(self):
        for _ in range(5):
            self.tenter("incorrect")

        self.assertEqual(TentativeConnexion.objects.count(), 1)
        tentative = TentativeConnexion.objects.get()
        self.assertEqual(tentative.nombre, 5)
        self.assertTrue(tentative.est_bloquee)
        self.assertEqual(self.tenter("MotDePasse!Fort2026").status_code, 200)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_connexion_reussie_efface_les_echecs_precedents(self):
        self.tenter("incorrect")
        self.assertEqual(TentativeConnexion.objects.get().nombre, 1)

        reponse = self.tenter("MotDePasse!Fort2026")

        self.assertEqual(reponse.status_code, 302)
        self.assertFalse(TentativeConnexion.objects.exists())


class TestsProfil(TestCase):
    def setUp(self):
        self.dossier_media = TemporaryDirectory()
        self.addCleanup(self.dossier_media.cleanup)
        parametres_media = override_settings(MEDIA_ROOT=self.dossier_media.name)
        parametres_media.enable()
        self.addCleanup(parametres_media.disable)
        self.utilisateur = Utilisateur.objects.create_user(
            "profil", "profil@example.test", "MotDePasse!Fort2026",
            first_name="Marie", last_name="Joseph",
        )
        etablissement = creer_etablissement("Établissement du profil", TypeEtablissement.SCOLAIRE)
        role = Role.sans_filtre.create(etablissement=etablissement, nom="Membre", codes=[])
        Appartenance.sans_filtre.create(
            utilisateur=self.utilisateur, etablissement=etablissement, role=role,
        )
        self.client.force_login(self.utilisateur)

    @staticmethod
    def creer_image():
        contenu = BytesIO()
        Image.new("RGB", (20, 20), color="teal").save(contenu, format="PNG")
        return SimpleUploadedFile("portrait.png", contenu.getvalue(), content_type="image/png")

    def test_page_profil_presente_le_formulaire_et_les_informations_de_compte(self):
        reponse = self.client.get(reverse("profil"))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Informations personnelles")
        self.assertContains(reponse, "Adresse e-mail de connexion")
        self.assertContains(reponse, 'enctype="multipart/form-data"')

    def test_profil_met_a_jour_les_informations_et_televerse_la_photo(self):
        reponse = self.client.post(reverse("profil"), {
            "first_name": "Marie-Claire",
            "last_name": "Joseph",
            "telephone": "44521822",
            "photo": self.creer_image(),
        })

        self.assertRedirects(reponse, reverse("profil"), fetch_redirect_response=False)
        self.utilisateur.refresh_from_db()
        self.assertEqual(self.utilisateur.first_name, "Marie-Claire")
        self.assertEqual(self.utilisateur.last_name, "Joseph")
        self.assertEqual(self.utilisateur.telephone, "44521822")
        self.assertEqual(self.utilisateur.email, "profil@example.test")
        self.assertTrue(self.utilisateur.photo.name.startswith("profils/"))
        self.assertTrue(self.utilisateur.photo.storage.exists(self.utilisateur.photo.name))
        self.assertContains(self.client.get(reverse("profil")), f'src="{self.utilisateur.photo.url}"')

    def test_profil_refuse_un_fichier_qui_nest_pas_une_image(self):
        reponse = self.client.post(reverse("profil"), {
            "first_name": "Marie",
            "last_name": "Joseph",
            "telephone": "",
            "photo": SimpleUploadedFile("portrait.svg", b"<svg/>", content_type="image/svg+xml"),
        })

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "image")
        self.utilisateur.refresh_from_db()
        self.assertFalse(self.utilisateur.photo)

    def test_profil_conserve_la_photo_si_aucune_nouvelle_image_nest_envoyee(self):
        self.client.post(reverse("profil"), {
            "first_name": "Marie",
            "last_name": "Joseph",
            "telephone": "",
            "photo": self.creer_image(),
        })
        self.utilisateur.refresh_from_db()
        photo_enregistree = self.utilisateur.photo.name

        reponse = self.client.post(reverse("profil"), {
            "first_name": "Marie-Claire",
            "last_name": "Joseph",
            "telephone": "",
        })

        self.assertRedirects(reponse, reverse("profil"), fetch_redirect_response=False)
        self.utilisateur.refresh_from_db()
        self.assertEqual(self.utilisateur.photo.name, photo_enregistree)
