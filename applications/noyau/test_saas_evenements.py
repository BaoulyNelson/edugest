from datetime import date

from django.test import TestCase

from applications.noyau.models import Appartenance, EvenementPaiement, UsageAbonnement
from applications.noyau.outils_tests import monde_scolaire

from . import saas


class TestsEvenementsEtUsageSaas(TestCase):
    def setUp(self):
        self.etablissement = monde_scolaire()["etab"]

    def test_evenement_idempotent_et_donnees_sensibles_filtrees(self):
        arguments = {
            "etablissement": self.etablissement,
            "fournisseur": "prestataire-test",
            "identifiant_externe": "evt-001",
            "type_evenement": EvenementPaiement.Type.PAIEMENT_REUSSI,
            "donnees": {"reference": "ref-123", "token": "ne-pas-conserver"},
        }
        premier, cree = saas.enregistrer_evenement_paiement(**arguments)
        second, nouveau = saas.enregistrer_evenement_paiement(**arguments)

        self.assertTrue(cree)
        self.assertFalse(nouveau)
        self.assertEqual(premier.pk, second.pk)
        self.assertEqual(EvenementPaiement.objects.count(), 1)
        self.assertEqual(premier.donnees, {"reference": "ref-123"})

    def test_mesure_usage_quotidienne_est_mise_a_jour_sans_doublon(self):
        jour = date(2026, 11, 9)

        premiere = saas.enregistrer_usage_abonnement(self.etablissement, jour)
        seconde = saas.enregistrer_usage_abonnement(self.etablissement, jour)

        self.assertEqual(premiere.pk, seconde.pk)
        self.assertEqual(UsageAbonnement.objects.filter(etablissement=self.etablissement, date=jour).count(), 1)
        self.assertEqual(
            premiere.nombre_membres,
            Appartenance.objects.filter(etablissement=self.etablissement, actif=True).count(),
        )
