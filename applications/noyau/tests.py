from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase

from applications.academique.models import AnneeAcademique
from applications.noyau.contexte import etablissement_courant
from applications.noyau.models import Appartenance, JournalAudit, Role
from applications.noyau.outils_tests import monde_scolaire
from applications.noyau.services import enregistrer_audit, servir_numero, verifier_permission


class TestsNoyau(TestCase):
    def setUp(self):
        self.a = monde_scolaire("École A")
        self.b = monde_scolaire("École B")

    def test_isolation_des_donnees_entre_etablissements(self):
        with etablissement_courant(self.a["etab"]):
            self.assertEqual(AnneeAcademique.objects.count(), 1)
            self.assertEqual(AnneeAcademique.objects.get().etablissement, self.a["etab"])
            self.assertFalse(AnneeAcademique.objects.filter(pk=self.b["annee"].pk).exists())
        with etablissement_courant(None):
            self.assertEqual(AnneeAcademique.objects.count(), 2)

    def test_aucun_etablissement_ne_voit_aucune_donnee(self):
        with etablissement_courant(type("E", (), {"pk": 0})()):
            self.assertEqual(AnneeAcademique.objects.count(), 0)

    def test_superutilisateur_conserve_l_acces_global_a_l_admin_django(self):
        administrateur = get_user_model().objects.create_superuser(
            username="admin_plateforme", email="admin@plateforme.test", password="MotDePasse!2026"
        )
        self.client.force_login(administrateur)
        session = self.client.session
        session["etablissement_id"] = self.a["etab"].pk
        session.save()

        reponse = self.client.get("/administration/academique/anneeacademique/")

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["cl"].queryset.count(), 2)
        self.assertEqual(self.client.session["etablissement_id"], self.a["etab"].pk)

    def test_ecriture_dans_un_autre_etablissement_refusee(self):
        with etablissement_courant(self.a["etab"]):
            with self.assertRaises(ValidationError):
                Role(etablissement=self.b["etab"], nom="Intrus", codes=[]).save()

    def test_permissions_par_role(self):
        e = self.a
        self.assertTrue(verifier_permission(e["prof"].utilisateur, e["prof"], "evaluations.saisir"))
        self.assertFalse(verifier_permission(e["prof"].utilisateur, e["prof"], "inscriptions.decider"))
        self.assertFalse(verifier_permission(e["secretaire"].utilisateur, e["secretaire"], "inscriptions.decider"))
        self.assertTrue(verifier_permission(e["directeur"].utilisateur, e["directeur"], "inscriptions.decider"))
        administrateur = get_user_model().objects.create_superuser(
            username="root_permission", email="root_permission@plateforme.test",
            password="MotDePasse!2026",
        )
        self.assertFalse(verifier_permission(administrateur, e["directeur"], "academique.gerer"))
        appartenance = Appartenance.sans_filtre.create(
            utilisateur=administrateur,
            etablissement=e["etab"],
            role=e["directeur"].role,
        )
        self.assertTrue(verifier_permission(administrateur, appartenance, "academique.gerer"))

    def test_sequence_sans_doublon(self):
        etab = self.a["etab"]
        self.assertEqual([servir_numero(etab, "x") for _ in range(3)], [1, 2, 3])
        self.assertEqual(servir_numero(self.b["etab"], "x"), 1)

    def test_journal_audit_immuable(self):
        ligne = enregistrer_audit(self.a["etab"], None, "test")
        with self.assertRaises(ValidationError):
            ligne.save()
        with self.assertRaises(ValidationError):
            ligne.delete()
        self.assertTrue(JournalAudit.objects.filter(pk=ligne.pk).exists())
