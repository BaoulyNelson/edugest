from django.test import TestCase
from django.urls import reverse

from applications.noyau.models import Utilisateur

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
