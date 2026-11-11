import smtplib
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from applications.apprenants.models import Apprenant, Inscription
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Invitation
from applications.noyau.outils_tests import monde_scolaire
from applications.noyau.services import creer_membre

from . import services
from .models import Candidature


class TestsAdmissions(TestCase):
    def setUp(self):
        self.m = monde_scolaire()

    def deposer(self, **overrides):
        donnees = {
            "etablissement": self.m["etab"].pk,
            "nom": "Jean",
            "prenoms": "Nina",
            "sexe": "F",
            "date_naissance": "2013-05-01",
            "lieu_naissance": "Port-au-Prince",
            "classe": self.m["classe_a"].pk,
            "nom_parent": "Marie Louis",
            "telephone_parent": "50912345678",
            "email_parent": "marie@example.test",
            "message": "Demande d'admission",
            "consentement": "on",
        }
        donnees.update(overrides)
        return self.client.post(reverse("admissions:deposer"), donnees)

    def test_depot_public_et_consentement(self):
        reponse = self.deposer()
        candidature = Candidature.sans_filtre.get()
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, str(candidature.reference))
        self.assertEqual(candidature.etablissement, self.m["etab"])
        self.assertEqual(candidature.annee, self.m["annee"])
        self.assertTrue(candidature.consentement_donnees)
        self.assertIsNotNone(candidature.consentement_le)

    def test_date_de_naissance_egale_a_aujourdhui_est_acceptee(self):
        from django.utils import timezone

        reponse = self.deposer(date_naissance=timezone.localdate().isoformat())
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(Candidature.sans_filtre.get().date_naissance, timezone.localdate())

    def test_classe_d_un_autre_etablissement_refusee(self):
        autre = monde_scolaire("Autre école")
        reponse = self.deposer(classe=autre["classe_a"].pk)
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Candidature.sans_filtre.exists())
        self.assertTrue(reponse.context["formulaire"].has_error("classe"))

    def test_liste_protegee_par_permission(self):
        self.assertEqual(self.client.get(reverse("admissions:liste")).status_code, 302)
        self.client.force_login(self.m["directeur"].utilisateur)
        self.assertEqual(self.client.get(reverse("admissions:liste")).status_code, 200)

    def test_tableau_de_bord_signale_les_candidatures_a_examiner(self):
        self.deposer()
        self.client.force_login(self.m["directeur"].utilisateur)
        reponse = self.client.get(reverse("tableau_de_bord"))
        indicateur = next(i for i in reponse.context["indicateurs"] if i[0] == "Candidatures à examiner")
        self.assertEqual(indicateur[1:], (1, "admissions:liste", "?statut=RECUE"))

    @mock.patch("applications.noyau.saas.send_mail", return_value=1)
    def test_acceptation_cree_inscription_validee_et_invite_parent(self, envoyer):
        self.deposer()
        candidature = Candidature.sans_filtre.get()
        self.client.force_login(self.m["directeur"].utilisateur)
        reponse = self.client.post(
            reverse("admissions:action", args=[candidature.reference]),
            {"action": "accepter"},
        )
        candidature.refresh_from_db()
        inscription = Inscription.sans_filtre.get(pk=candidature.inscription_creee_id)
        invitation = Invitation.sans_filtre.get(responsable__email="marie@example.test")
        self.assertRedirects(reponse, reverse("admissions:detail", args=[candidature.reference]))
        self.assertEqual(candidature.statut, Candidature.Statut.ACCEPTEE)
        self.assertEqual(candidature.apprenant_cree.nom, "JEAN")
        self.assertEqual(inscription.statut, Inscription.Statut.VALIDEE)
        self.assertEqual(invitation.email, "marie@example.test")
        self.assertEqual(Apprenant.sans_filtre.count(), 1)
        envoyer.assert_called_once()

    @mock.patch("applications.noyau.saas.send_mail", side_effect=smtplib.SMTPException("SMTP indisponible"))
    def test_echec_envoi_annule_acceptation_sans_creer_le_dossier(self, envoyer):
        self.deposer()
        candidature = Candidature.sans_filtre.get()
        with self.assertRaises(ErreurMetier):
            services.accepter_candidature(candidature, self.m["directeur"].utilisateur, "https://ecole.test")
        candidature.refresh_from_db()
        self.assertEqual(candidature.statut, Candidature.Statut.RECUE)
        self.assertFalse(Apprenant.sans_filtre.exists())
        self.assertFalse(Inscription.sans_filtre.exists())
        envoyer.assert_called_once()

    @mock.patch("applications.noyau.saas.send_mail", return_value=1)
    def test_parent_deja_membre_est_associe_sans_nouvelle_invitation(self, envoyer):
        compte = creer_membre(
            self.m["etab"], "parent_marie", "marie@example.test", "MotDePasse!2026", "Parent"
        ).utilisateur
        self.deposer()
        candidature = Candidature.sans_filtre.get()
        _, invitation = services.accepter_candidature(
            candidature, self.m["directeur"].utilisateur, "https://ecole.test"
        )
        candidature.refresh_from_db()
        self.assertIsNone(invitation)
        self.assertEqual(candidature.apprenant_cree.liens_responsables.get().responsable.utilisateur, compte)
        self.assertFalse(Invitation.sans_filtre.exists())
        envoyer.assert_not_called()

    def test_refus_conserve_le_dossier_et_le_motif(self):
        self.deposer()
        candidature = Candidature.sans_filtre.get()
        services.refuser_candidature(candidature, self.m["directeur"].utilisateur, "Places indisponibles")
        candidature.refresh_from_db()
        self.assertEqual(candidature.statut, Candidature.Statut.REFUSEE)
        self.assertEqual(candidature.motif_decision, "Places indisponibles")
        self.assertFalse(Apprenant.sans_filtre.exists())

    def test_candidature_deja_traitee_ne_peut_pas_etre_reacceptee(self):
        self.deposer()
        candidature = Candidature.sans_filtre.get()
        services.refuser_candidature(candidature, self.m["directeur"].utilisateur)
        with self.assertRaises(ErreurMetier):
            services.refuser_candidature(candidature, self.m["directeur"].utilisateur)
