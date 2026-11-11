import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from applications.apprenants.models import LienResponsable, ResponsableLegal
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.noyau.services import creer_membre

from .models import (
    Devoir, EntreeCahier, NotificationCahier, PieceJointeDevoir, PieceJointeRemise, Remise,
)


class TestsCahierEtDevoirs(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.TemporaryDirectory(prefix="edugest-cahier-")
        cls._settings = override_settings(
            MEDIA_ROOT=Path(cls._media.name) / "public",
            PRIVATE_MEDIA_ROOT=Path(cls._media.name) / "prive",
        )
        cls._settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        cls._media.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.monde = monde_scolaire()
        self.inscription = inscrire(self.monde, "Élève Cahier")
        self.eleve = creer_membre(
            self.monde["etab"], "eleve_cahier", "eleve-cahier@ecole.test",
            "MotDePasse!2026", "Apprenant",
        )
        self.inscription.apprenant.utilisateur = self.eleve.utilisateur
        self.inscription.apprenant.save(update_fields=["utilisateur"])
        self.parent = creer_membre(
            self.monde["etab"], "parent_cahier", "parent-cahier@ecole.test",
            "MotDePasse!2026", "Parent",
        )
        responsable = ResponsableLegal.objects.create(
            etablissement=self.monde["etab"],
            nom="Responsable Cahier",
            utilisateur=self.parent.utilisateur,
        )
        LienResponsable.objects.create(
            etablissement=self.monde["etab"],
            apprenant=self.inscription.apprenant,
            responsable=responsable,
        )

    def fichier(self, nom="travail.pdf", contenu=b"%PDF-1.4 test"):
        return SimpleUploadedFile(nom, contenu, content_type="application/pdf")

    def publier_devoir(
        self, fichier=None, limite=None, accepter_tardif=True, modifier_apres=True, bareme="100",
    ):
        self.client.force_login(self.monde["prof"].utilisateur)
        donnees = {
            "classe": self.monde["classe_a"].pk,
            "matiere_niveau": self.monde["mn"].pk,
            "titre": "Exercices de calcul",
            "consigne": "Faire les exercices 1 à 5.",
            "date_limite": (limite or timezone.localdate() + timedelta(days=3)).isoformat(),
            "remise_numerique": "on",
            "accepter_remises_tardives": "on" if accepter_tardif else "",
            "modifier_apres_echeance": "on" if modifier_apres else "",
            "bareme": bareme,
        }
        if fichier:
            donnees["fichiers"] = fichier
        return self.client.post(reverse("cahier:devoir_creer"), donnees)

    def test_seance_et_devoir_sont_limites_aux_affectations(self):
        self.client.force_login(self.monde["prof"].utilisateur)
        seance = {
            "classe": self.monde["classe_a"].pk,
            "matiere_niveau": self.monde["mn"].pk,
            "date": timezone.localdate().isoformat(),
            "titre": "Fractions",
            "contenu": "Cours sur les fractions.",
        }
        self.assertEqual(self.client.post(reverse("cahier:entree_creer"), seance).status_code, 302)
        self.assertEqual(EntreeCahier.objects.count(), 1)

        seance["classe"] = self.monde["classe_b"].pk
        self.assertEqual(self.client.post(reverse("cahier:entree_creer"), seance).status_code, 200)
        self.assertEqual(EntreeCahier.objects.count(), 1)

        reponse = self.publier_devoir()
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Devoir.objects.count(), 1)
        self.client.force_login(self.parent.utilisateur)
        cahier_parent = self.client.get(reverse("cahier:mon_cahier"))
        self.assertContains(cahier_parent, "Exercices de calcul")
        self.assertContains(cahier_parent, "7e année")
        self.assertContains(cahier_parent, "7e A")
        self.assertEqual(
            NotificationCahier.objects.filter(destinataire__in=[
                self.parent.utilisateur, self.eleve.utilisateur,
            ]).count(),
            2,
        )

    def test_depot_remplacement_et_appreciation_du_travail(self):
        self.publier_devoir()
        devoir = Devoir.objects.get()
        self.client.force_login(self.eleve.utilisateur)
        self.assertContains(self.client.get(reverse("cahier:devoir", args=[devoir.pk])), "Déposer mon travail")
        reponse = self.client.post(
            reverse("cahier:devoir", args=[devoir.pk]),
            {"fichier": self.fichier(), "commentaire": "Voici mon travail."},
        )
        self.assertEqual(reponse.status_code, 302)
        remise = Remise.objects.get()
        self.assertFalse(remise.en_retard)
        self.assertTrue(Path(remise.fichier.path).is_relative_to(Path(self._media.name) / "prive"))
        self.assertFalse(Path(remise.fichier.path).is_relative_to(Path(self._media.name) / "public"))
        telechargement = self.client.get(reverse("cahier:telecharger", args=["remise", remise.pk]))
        self.assertEqual(telechargement.status_code, 200)
        telechargement.close()
        self.assertEqual(
            self.client.get(f"/media/{remise.fichier.name}").status_code,
            404,
        )

        self.client.post(
            reverse("cahier:devoir", args=[devoir.pk]),
            {"fichier": self.fichier("remplacement.pdf"), "commentaire": "Version corrigée."},
        )
        remise.refresh_from_db()
        self.assertEqual(Remise.objects.count(), 1)
        self.assertEqual(remise.commentaire, "Version corrigée.")

        self.client.force_login(self.monde["prof"].utilisateur)
        reponse = self.client.post(
            reverse("cahier:apprecier", args=[remise.pk]),
            {"appreciation": "Très bien."},
        )
        self.assertEqual(reponse.status_code, 302)
        remise.refresh_from_db()
        self.assertEqual(remise.appreciation, "Très bien.")
        self.client.force_login(self.eleve.utilisateur)
        self.assertContains(self.client.get(reverse("cahier:devoir", args=[devoir.pk])), "Très bien.")

    def test_remise_tardive_et_fichiers_invalides_refuses(self):
        self.publier_devoir(limite=timezone.localdate() - timedelta(days=1))
        devoir = Devoir.objects.get()
        self.client.force_login(self.eleve.utilisateur)
        reponse = self.client.post(
            reverse("cahier:devoir", args=[devoir.pk]),
            {"fichier": self.fichier(), "commentaire": ""},
        )
        self.assertTrue(Remise.objects.get().en_retard)

        autre_devoir = self.monde["classe_a"].devoirs.create(
            etablissement=self.monde["etab"],
            matiere_niveau=self.monde["mn"],
            enseignant=self.monde["prof"],
            titre="Devoir fichier",
            consigne="Consigne",
            date_limite=timezone.localdate() + timedelta(days=2),
        )
        self.client.post(
            reverse("cahier:devoir", args=[autre_devoir.pk]),
            {"fichier": SimpleUploadedFile("virus.exe", b"MZ"), "commentaire": ""},
        )
        with override_settings(TAILLE_MAX_FICHIER_MO=1):
            self.client.post(
                reverse("cahier:devoir", args=[autre_devoir.pk]),
                {"fichier": self.fichier("gros.pdf", b"0" * (1024 * 1024 + 1)), "commentaire": ""},
            )
        self.assertFalse(Remise.objects.filter(devoir=autre_devoir).exists())

    def test_parent_d_une_autre_classe_ne_peut_pas_ouvrir_le_devoir(self):
        self.publier_devoir()
        devoir = Devoir.objects.get()
        autre_inscription = inscrire(self.monde, "Élève autre classe", self.monde["classe_b"])
        autre_parent = creer_membre(
            self.monde["etab"], "parent_autre_cahier", "parent-autre-cahier@ecole.test",
            "MotDePasse!2026", "Parent",
        )
        responsable = ResponsableLegal.objects.create(
            etablissement=self.monde["etab"],
            nom="Autre responsable",
            utilisateur=autre_parent.utilisateur,
        )
        LienResponsable.objects.create(
            etablissement=self.monde["etab"],
            apprenant=autre_inscription.apprenant,
            responsable=responsable,
        )
        self.client.force_login(autre_parent.utilisateur)
        self.assertEqual(self.client.get(reverse("cahier:devoir", args=[devoir.pk])).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("cahier:telecharger", args=["devoir", devoir.pk])).status_code,
            403,
        )

    def test_cahier_eleve_affiche_classe_et_devoirs_anciens_de_la_classe(self):
        self.publier_devoir(limite=timezone.localdate() - timedelta(days=60))
        devoir = Devoir.objects.get()
        self.client.force_login(self.eleve.utilisateur)

        cahier = self.client.get(reverse("cahier:mon_cahier"))

        self.assertEqual(cahier.status_code, 200)
        self.assertContains(cahier, "Ma classe et mon niveau")
        self.assertContains(cahier, "7e année")
        self.assertContains(cahier, "7e A")
        self.assertContains(cahier, "Exercices de calcul")
        self.assertContains(cahier, "En retard — non rendu")
        self.assertContains(cahier, reverse("cahier:devoir", args=[devoir.pk]))
        tableau = self.client.get(reverse("tableau_de_bord"))
        self.assertContains(tableau, "Ma classe et mon niveau")
        self.assertContains(tableau, "7e année")
        self.assertContains(tableau, "7e A")
        self.assertContains(tableau, "Suivi de mes devoirs")

    def test_badge_de_correction_reste_visible_jusqua_ouverture_du_devoir(self):
        self.publier_devoir()
        devoir = Devoir.objects.get()
        self.client.force_login(self.eleve.utilisateur)
        self.client.post(
            reverse("cahier:devoir", args=[devoir.pk]),
            {"fichier": self.fichier(), "commentaire": ""},
        )
        remise = Remise.objects.get()

        self.client.force_login(self.monde["prof"].utilisateur)
        self.client.post(
            reverse("cahier:remise_correction", args=[remise.pk]),
            {"note": "98", "appreciation": "Très bon travail."},
        )
        notification = NotificationCahier.objects.get(
            destinataire=self.eleve.utilisateur,
            url=reverse("cahier:devoir", args=[devoir.pk]),
            titre__startswith="Travail corrigé :",
        )
        self.assertFalse(notification.lue)

        self.client.force_login(self.eleve.utilisateur)
        self.assertContains(self.client.get(reverse("cahier:mon_cahier")), "Nouveau")
        tableau = self.client.get(reverse("tableau_de_bord"))
        self.assertContains(tableau, "Devoirs corrigés")
        self.assertContains(tableau, "Nouveau")
        notification.refresh_from_db()
        self.assertFalse(notification.lue)

        self.client.get(reverse("cahier:devoir", args=[devoir.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.lue)

    def test_pieces_jointes_multiples_correction_et_note_visible_a_leleve(self):
        self.publier_devoir(fichier=[
            self.fichier("consigne.pdf"),
            self.fichier("schema.png", b"image"),
        ], bareme="20")
        devoir = Devoir.objects.get()
        self.assertEqual(PieceJointeDevoir.objects.filter(devoir=devoir).count(), 1)

        self.client.force_login(self.eleve.utilisateur)
        reponse = self.client.post(
            reverse("cahier:devoir", args=[devoir.pk]),
            {"fichier": [self.fichier(), self.fichier("reponses.jpg", b"image")],
             "commentaire": "Réponses jointes."},
        )
        self.assertEqual(reponse.status_code, 302)
        remise = Remise.objects.get()
        self.assertEqual(PieceJointeRemise.objects.filter(remise=remise).count(), 1)
        self.assertTrue(Path(PieceJointeRemise.objects.get().fichier.path).is_relative_to(
            Path(self._media.name) / "prive"
        ))
        self.client.force_login(self.eleve.utilisateur)
        self.assertNotContains(
            self.client.get(reverse("cahier:devoir", args=[devoir.pk])),
            "Correction de l'enseignant",
        )

        self.client.force_login(self.monde["prof"].utilisateur)
        correction_url = reverse("cahier:remise_correction", args=[remise.pk])
        self.assertContains(self.client.get(correction_url), "reponses.jpg")
        reponse = self.client.post(
            correction_url,
            {"note": "20.01", "appreciation": "Cette note dépasse le barème."},
        )
        self.assertEqual(reponse.status_code, 200)
        remise.refresh_from_db()
        self.assertIsNone(remise.note)
        reponse = self.client.post(
            correction_url,
            {"note": "17.5", "appreciation": "Excellent travail."},
        )
        self.assertEqual(reponse.status_code, 302)
        remise.refresh_from_db()
        self.assertEqual(str(remise.note), "17.50")
        self.assertIsNotNone(remise.corrige_le)
        self.assertEqual(remise.correcteur_id, self.monde["prof"].utilisateur.pk)

        self.client.force_login(self.eleve.utilisateur)
        page = self.client.get(reverse("cahier:devoir", args=[devoir.pk]))
        self.assertContains(
            page,
            "17,50 / 20,00",
        )
        telechargement = self.client.get(reverse("cahier:telecharger", args=[
            "piece_remise", PieceJointeRemise.objects.get().pk,
        ]))
        self.assertEqual(telechargement.status_code, 200)
        self.assertEqual(b"".join(telechargement.streaming_content), b"image")
        telechargement.close()

    def test_parametres_bloquent_depots_tardifs_et_modifications_apres_echeance(self):
        self.publier_devoir(
            limite=timezone.localdate() - timedelta(days=1),
            accepter_tardif=False,
        )
        devoir = Devoir.objects.get()
        self.client.force_login(self.eleve.utilisateur)
        self.assertContains(
            self.client.get(reverse("cahier:devoir", args=[devoir.pk])),
            "ne permettent plus",
        )
        self.assertEqual(
            self.client.post(
                reverse("cahier:devoir", args=[devoir.pk]),
                {"fichier": self.fichier(), "commentaire": ""},
            ).status_code,
            200,
        )
        self.assertFalse(Remise.objects.exists())

        self.publier_devoir()
        devoir = Devoir.objects.order_by("-pk").first()
        self.client.force_login(self.eleve.utilisateur)
        self.client.post(
            reverse("cahier:devoir", args=[devoir.pk]),
            {"fichier": self.fichier(), "commentaire": "Première version."},
        )
        devoir.date_limite = timezone.localdate() - timedelta(days=1)
        devoir.modifier_apres_echeance = False
        devoir.save(update_fields=["date_limite", "modifier_apres_echeance"])
        self.assertEqual(
            self.client.post(
                reverse("cahier:devoir", args=[devoir.pk]),
                {"fichier": self.fichier("version-2.pdf"), "commentaire": "Nouvelle version."},
            ).status_code,
            200,
        )
        remise = Remise.objects.get(devoir=devoir)
        self.assertEqual(remise.commentaire, "Première version.")
