from django.test import TestCase
from django.urls import reverse

from applications.apprenants import services as services_apprenants
from applications.apprenants.models import Inscription, LienResponsable
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.noyau.services import creer_membre

from applications.admissions.models import Candidature
from . import services
from .models import Consentement, DemandeRGPD


class TestsRGPD(TestCase):
    def setUp(self):
        self.monde = monde_scolaire("École RGPD")
        self.inscription = inscrire(self.monde, "Test")
        self.apprenant = self.inscription.apprenant
        self.responsable = services_apprenants.creer_responsable(
            self.monde["etab"], "Parent", "Test", "555-0101", "parent@example.test"
        )
        LienResponsable.sans_filtre.create(
            etablissement=self.monde["etab"], apprenant=self.apprenant,
            responsable=self.responsable, lien="TUTEUR", principal=True,
        )
        self.parent = creer_membre(
            self.monde["etab"], "parent_test", "parent@example.test",
            "MotDePasse!2026", "Parent",
        )
        self.responsable.utilisateur = self.parent.utilisateur
        self.responsable.save(update_fields=["utilisateur"])

    def test_parent_peut_exporter_les_donnees_de_son_enfant(self):
        Candidature.sans_filtre.create(
            etablissement=self.monde["etab"], annee=self.monde["annee"], classe=self.monde["classe_a"],
            nom=self.apprenant.nom, prenoms=self.apprenant.prenoms, date_naissance=self.apprenant.date_naissance,
            nom_parent=self.responsable.nom, telephone_parent=self.responsable.telephone,
            email_parent=self.responsable.email, apprenant_cree=self.apprenant,
        )
        self.client.force_login(self.parent.utilisateur)
        reponse = self.client.get(reverse("rgpd:exporter", args=[self.apprenant.pk]))

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/json")
        self.assertContains(reponse, "date_naissance")
        self.assertContains(reponse, self.apprenant.nom)
        self.assertContains(reponse, "candidatures")

    def test_un_compte_sans_lien_ne_peut_pas_exporter_le_dossier(self):
        autre = creer_membre(
            self.monde["etab"], "autre_parent", "autre@example.test",
            "MotDePasse!2026", "Parent",
        )
        self.client.force_login(autre.utilisateur)

        self.assertEqual(self.client.get(reverse("rgpd:exporter", args=[self.apprenant.pk])).status_code, 404)

    def test_anonymisation_refuse_une_inscription_de_l_annee_active(self):
        with self.assertRaisesMessage(ErreurMetier, "inscription en cours"):
            services.anonymiser_apprenant(self.apprenant, self.monde["directeur"].utilisateur)
        self.apprenant.refresh_from_db()
        self.assertFalse(self.apprenant.anonymise)

    def test_anonymisation_preserve_l_inscription_historique(self):
        self.monde["annee"].statut = "CLOTUREE"
        self.monde["annee"].save(update_fields=["statut"])
        candidature = Candidature.sans_filtre.create(
            etablissement=self.monde["etab"], annee=self.monde["annee"], classe=self.monde["classe_a"],
            nom=self.apprenant.nom, prenoms=self.apprenant.prenoms, date_naissance=self.apprenant.date_naissance,
            nom_parent=self.responsable.nom, telephone_parent=self.responsable.telephone,
            email_parent=self.responsable.email, apprenant_cree=self.apprenant,
        )

        services.anonymiser_apprenant(self.apprenant, self.monde["directeur"].utilisateur)

        self.apprenant.refresh_from_db()
        self.inscription.refresh_from_db()
        self.assertTrue(self.apprenant.anonymise)
        self.assertEqual(self.apprenant.nom, "Dossier anonymisé")
        self.assertEqual(self.apprenant.email, "")
        self.assertEqual(self.apprenant.sexe, "")
        self.assertEqual(self.apprenant.matricule, f"ANON-{self.apprenant.pk}")
        self.assertEqual(self.inscription.statut, Inscription.Statut.VALIDEE)
        candidature.refresh_from_db()
        self.assertEqual(candidature.nom, "Dossier anonymisé")
        self.assertEqual(candidature.email_parent, "")
        self.parent.utilisateur.refresh_from_db()
        self.assertFalse(self.parent.utilisateur.is_active)

    def test_creation_de_demande_et_historique_de_consentement(self):
        demande = services.creer_demande(
            self.apprenant, self.parent.utilisateur, DemandeRGPD.Type.ACCES, "Copie de mes données"
        )
        consentement = services.enregistrer_consentement(
            self.apprenant, Consentement.Finalite.IMAGE, True, "Photo de classe",
            self.monde["directeur"].utilisateur,
        )

        self.assertEqual(demande.demandeur, self.parent.utilisateur)
        self.assertEqual(consentement.apprenant, self.apprenant)
        self.assertTrue(consentement.accorde)
        self.assertEqual(Consentement.objects.count(), 1)
