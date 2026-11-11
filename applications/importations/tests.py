from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from applications.apprenants.models import Apprenant, Inscription
from applications.importations.models import LotImportation
from applications.noyau.models import Invitation
from applications.noyau.outils_tests import monde_scolaire


class TestsImportations(TestCase):
    def setUp(self):
        self.monde = monde_scolaire("École Import")
        self.client.force_login(self.monde["secretaire"].utilisateur)

    def envoyer(self, type_import, contenu, nom="import.csv", utilisateur=None):
        if utilisateur:
            self.client.force_login(utilisateur)
        fichier = SimpleUploadedFile(nom, contenu.encode("utf-8"), content_type="text/csv")
        return self.client.post(reverse("importations:accueil"), {
            "type_import": type_import, "fichier": fichier,
        })

    def test_import_apprenants_est_previsualise_puis_cree_avec_inscription(self):
        contenu = (
            "nom,prenoms,sexe,date_naissance,niveau,classe\n"
            "Jean,Marie,F,2013-04-12,7e année,7e A\n"
        )
        reponse = self.envoyer("APPRENANTS", contenu)
        self.assertEqual(reponse.status_code, 302)
        lot = LotImportation.objects.get()
        self.assertEqual(Apprenant.objects.count(), 0)
        self.assertEqual(lot.nombre_valide, 1)

        reponse = self.client.post(reverse("importations:confirmer", args=[lot.pk]))

        self.assertRedirects(reponse, reverse("apprenants:liste"), fetch_redirect_response=False)
        apprenant = Apprenant.objects.get()
        inscription = Inscription.objects.get(apprenant=apprenant)
        self.assertEqual(inscription.niveau, self.monde["n7"])
        self.assertEqual(inscription.classe, self.monde["classe_a"])
        self.assertEqual(inscription.statut, Inscription.Statut.EN_ATTENTE)
        lot.refresh_from_db()
        self.assertEqual(lot.lignes, [])
        self.assertEqual(lot.nombre_importe, 1)

    def test_lignes_invalides_sont_affichees_sans_creer_de_dossier(self):
        reponse = self.envoyer(
            "APPRENANTS", "nom,prenoms,sexe,date_naissance\nJean,Marie,X,2013-04-12\n"
        )
        self.assertEqual(reponse.status_code, 302)
        lot = LotImportation.objects.get()
        self.assertEqual(lot.nombre_valide, 0)
        self.assertEqual(lot.nombre_erreurs, 1)
        self.assertEqual(Apprenant.objects.count(), 0)

    def test_import_personnel_envoie_une_invitation_sans_creer_de_mot_de_passe(self):
        reponse = self.envoyer(
            "PERSONNEL",
            "nom,prenoms,email,role\nDupont,Jean,jean.dupont@example.test,Enseignant\n",
            utilisateur=self.monde["directeur"].utilisateur,
        )
        self.assertEqual(reponse.status_code, 302, reponse.content.decode())
        from applications.importations.models import LotImportation

        lot = LotImportation.objects.get()
        self.assertEqual(lot.nombre_valide, 1)
        self.client.post(reverse("importations:confirmer", args=[lot.pk]))

        invitation = Invitation.objects.get(email="jean.dupont@example.test")
        self.assertEqual(invitation.role.nom, "Enseignant")
        self.assertEqual(invitation.invitee_par, self.monde["directeur"].utilisateur)

    def test_fichier_avec_extension_non_supportee_est_refuse(self):
        fichier = SimpleUploadedFile("import.txt", b"texte")
        reponse = self.client.post(reverse("importations:accueil"), {
            "type_import": "APPRENANTS", "fichier": fichier,
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Apprenant.objects.exists())
