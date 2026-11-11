from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from applications.apprenants import services as services_apprenants
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import JournalAudit
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.noyau.services import creer_membre

from . import services
from .models import Depense, Facture, Paiement


class TestsFinances(TestCase):
    def setUp(self):
        self.m = monde_scolaire("École Finance")
        self.inscription = inscrire(self.m, "Compta")
        self.comptable = creer_membre(
            self.m["etab"], "comptable", "comptable@finance.test", "MotDePasse!2026", "Comptable"
        )
        self.client.force_login(self.comptable.utilisateur)

    def test_comptable_accede_aux_paiements_depenses_et_rapports(self):
        for route in ("finances:paiements", "finances:depenses", "finances:rapports"):
            self.assertEqual(self.client.get(reverse(route)).status_code, 200, route)
        self.assertContains(self.client.get(reverse("tableau_de_bord")), "Paiements")

    def test_enregistrement_d_un_paiement_est_trace_et_isole(self):
        reponse = self.client.post(reverse("finances:paiement_creer"), {
            "apprenant": self.inscription.apprenant_id,
            "montant": "1250.00",
            "date_paiement": "2026-09-10",
            "motif": "Frais d'inscription",
            "mode": "ESPECES",
        })
        self.assertRedirects(reponse, reverse("finances:paiements"), fetch_redirect_response=False)
        paiement = Paiement.objects.get()
        self.assertEqual(paiement.montant, Decimal("1250.00"))
        self.assertEqual(paiement.etablissement_id, self.m["etab"].pk)
        self.assertTrue(JournalAudit.objects.filter(action="finance.paiement.enregistrement").exists())

    def test_enregistrement_d_une_depense_alimente_le_rapport(self):
        self.client.post(reverse("finances:paiement_creer"), {
            "apprenant": self.inscription.apprenant_id, "montant": "200.00",
            "date_paiement": "2026-09-10", "motif": "Frais scolaires", "mode": "VIREMENT",
        })
        reponse = self.client.post(reverse("finances:depense_creer"), {
            "montant": "50.00", "date_depense": "2026-09-11",
            "categorie": "FOURNITURES", "motif": "Cahiers",
        })
        self.assertRedirects(reponse, reverse("finances:depenses"), fetch_redirect_response=False)
        depense = Depense.objects.get()
        self.assertEqual(depense.etablissement_id, self.m["etab"].pk)
        rapport = self.client.get(reverse("finances:rapports"))
        self.assertEqual(rapport.context["synthese"]["solde"], Decimal("150.00"))

    def test_enseignant_sans_permission_ne_peut_pas_consulter_les_finances(self):
        self.client.force_login(self.m["prof"].utilisateur)
        self.assertEqual(self.client.get(reverse("finances:paiements")).status_code, 403)
        self.assertEqual(self.client.post(reverse("finances:depense_creer")).status_code, 403)

    def creer_facture(self, montant="1000.00", echeances=2):
        type_frais = services.creer_type_frais(self.m["etab"], "Scolarité")
        services.creer_grille_frais(
            self.m["etab"], self.m["annee"], self.m["n7"], type_frais,
            Decimal(montant), echeances, date(2026, 9, 1), self.comptable.utilisateur,
        )
        return services.generer_facture(self.inscription, self.comptable.utilisateur)

    def test_validation_emet_une_facture_et_repartit_les_echeances(self):
        type_frais = services.creer_type_frais(self.m["etab"], "Scolarité")
        services.creer_grille_frais(
            self.m["etab"], self.m["annee"], self.m["n7"], type_frais,
            Decimal("1000.00"), 3, date(2026, 9, 1), self.comptable.utilisateur,
        )
        nouvelle = inscrire(self.m, "Nouveau", valider=False)

        services_apprenants.decider_inscription(
            nouvelle, "VALIDER", self.m["secretaire"].utilisateur
        )

        facture = Facture.objects.get(inscription=nouvelle)
        self.assertEqual(facture.total, Decimal("1000.00"))
        self.assertEqual(list(facture.echeances.values_list("montant", flat=True)), [
            Decimal("333.33"), Decimal("333.33"), Decimal("333.34"),
        ])

    def test_encaissement_partiel_met_a_jour_le_solde_et_genere_un_recu_pdf(self):
        facture = self.creer_facture()
        paiement = services.encaisser_facture(
            facture, Decimal("250.00"), Paiement.Mode.ESPECES, "Caisse 12", self.comptable.utilisateur
        )
        facture.refresh_from_db()
        self.assertEqual(facture.statut, Facture.Statut.PARTIELLE)
        self.assertEqual(services.solde_facture(facture), Decimal("750.00"))
        self.assertTrue(paiement.numero_recu)

        reponse = self.client.get(reverse("finances:recu", args=[paiement.pk]))

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertEqual(paiement.affectations.count(), 1)

    def test_remboursement_trace_et_recalcule_le_solde_facture(self):
        facture = self.creer_facture()
        paiement = services.encaisser_facture(
            facture, Decimal("250.00"), Paiement.Mode.ESPECES, par=self.comptable.utilisateur
        )

        remboursement = services.enregistrer_remboursement(
            paiement, Decimal("50.00"), "Trop-perçu", self.comptable.utilisateur
        )

        facture.refresh_from_db()
        self.assertEqual(remboursement.montant, Decimal("50.00"))
        self.assertEqual(services.total_paye(facture), Decimal("200.00"))
        self.assertEqual(services.solde_facture(facture), Decimal("800.00"))
        self.assertEqual(facture.statut, Facture.Statut.PARTIELLE)
        with self.assertRaises(ErreurMetier):
            services.enregistrer_remboursement(
                paiement, Decimal("201.00"), "Dépassement", self.comptable.utilisateur
            )


    def test_facture_refuse_un_paiement_superieur_au_solde(self):
        facture = self.creer_facture()
        with self.assertRaisesMessage(ErreurMetier, "ne pas dépasser le solde"):
            services.encaisser_facture(
                facture, Decimal("1000.01"), Paiement.Mode.ESPECES, par=self.comptable.utilisateur
            )

    def test_grille_tarif_et_rapport_sont_accessibles_aux_comptables(self):
        self.assertEqual(self.client.get(reverse("finances:tarifs")).status_code, 200)
        self.assertEqual(self.client.get(reverse("finances:factures")).status_code, 200)
        rapport = self.client.get(reverse("finances:rapports"))
        self.assertEqual(rapport.status_code, 200)
        self.assertContains(rapport, "Période du rapport")
