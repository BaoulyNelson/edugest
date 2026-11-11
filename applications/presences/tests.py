from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from applications.apprenants.models import LienResponsable, ResponsableLegal
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.noyau.services import creer_membre

from . import services
from .models import AppelPresence, LignePresence, NotificationPresence


class TestsPresence(TestCase):
    def setUp(self):
        self.monde = monde_scolaire()
        self.inscription = inscrire(self.monde, "Absent")
        self.client.force_login(self.monde["prof"].utilisateur)

    def test_appel_enregistre_et_met_a_jour_les_statuts(self):
        aujourd_hui = timezone.localdate()
        url = reverse("presences:appel")
        reponse = self.client.get(url)
        self.assertContains(reponse, "Appel des présences")
        self.assertContains(reponse, str(self.inscription.apprenant))

        donnees = {
            "classe": self.monde["classe_a"].pk,
            "date": aujourd_hui.isoformat(),
            "enregistrer": "1",
            f"statut_{self.inscription.pk}": LignePresence.Statut.ABSENT,
            f"motif_{self.inscription.pk}": "Maladie",
        }
        reponse = self.client.post(url, donnees)
        self.assertRedirects(
            reponse, f"{url}?classe={self.monde['classe_a'].pk}&date={aujourd_hui.isoformat()}",
        )
        appel = AppelPresence.objects.get(classe=self.monde["classe_a"], date=aujourd_hui)
        ligne = LignePresence.objects.get(appel=appel, inscription=self.inscription)
        self.assertEqual((ligne.statut, ligne.motif), (LignePresence.Statut.ABSENT, "Maladie"))
        self.assertEqual(NotificationPresence.objects.count(), 0)

        donnees[f"statut_{self.inscription.pk}"] = LignePresence.Statut.RETARD
        self.client.post(url, donnees)
        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, LignePresence.Statut.RETARD)
        self.assertEqual(LignePresence.objects.filter(appel=appel).count(), 1)

    def test_enseignant_ne_peut_pas_prendre_l_appel_d_une_autre_classe(self):
        url = reverse("presences:appel")
        reponse = self.client.post(url, {
            "classe": self.monde["classe_b"].pk,
            "date": timezone.localdate().isoformat(),
            "enregistrer": "1",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(AppelPresence.objects.filter(classe=self.monde["classe_b"]).exists())

    def test_service_refuse_date_future_et_classe_non_affectee(self):
        with self.assertRaises(ErreurMetier):
            services.obtenir_appel(
                self.monde["classe_a"], timezone.localdate() + timedelta(days=1),
                self.monde["prof"].utilisateur,
            )
        appel = services.obtenir_appel(
            self.monde["classe_b"], timezone.localdate(), self.monde["prof"].utilisateur,
        )
        with self.assertRaises(ErreurMetier):
            services.enregistrer_appel(
                appel, {}, self.monde["prof"], self.monde["prof"].utilisateur,
            )

    def test_historique_restreint_a_la_permission(self):
        directeur = self.monde["directeur"]
        self.client.force_login(directeur.utilisateur)
        self.assertEqual(self.client.get(reverse("presences:liste")).status_code, 200)
        self.client.force_login(self.monde["secretaire"].utilisateur)
        self.assertEqual(self.client.get(reverse("presences:liste")).status_code, 403)

    def test_portail_famille_ne_montre_que_son_dossier(self):
        parent = creer_membre(
            self.monde["etab"], "parent_presence", "parent-presence@ecole.test",
            "MotDePasse!2026", "Parent",
        )
        apprenant = self.inscription.apprenant
        responsable = ResponsableLegal.objects.create(
            etablissement=self.monde["etab"], nom="Responsable", utilisateur=parent.utilisateur,
        )
        LienResponsable.objects.create(
            etablissement=self.monde["etab"], apprenant=apprenant, responsable=responsable,
        )
        autre = inscrire(self.monde, "Autre")
        appel = services.obtenir_appel(
            self.monde["classe_a"], timezone.localdate(), self.monde["prof"].utilisateur,
        )
        services.enregistrer_appel(appel, {
            self.inscription.pk: (LignePresence.Statut.ABSENT, "Malade"),
            autre.pk: (LignePresence.Statut.RETARD, ""),
        }, self.monde["prof"], self.monde["prof"].utilisateur)

        self.client.force_login(parent.utilisateur)
        reponse = self.client.get(reverse("presences:mes_absences"))
        self.assertContains(reponse, str(apprenant))
        self.assertNotContains(reponse, str(autre.apprenant))
        self.assertContains(reponse, "Malade")
        self.assertEqual(NotificationPresence.objects.filter(destinataire=parent.utilisateur, lue=True).count(), 1)
