from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from unittest import mock

from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance, Invitation, Role, TypeEtablissement
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.noyau.services import creer_etablissement, creer_membre
from applications.pedagogie import services
from applications.pedagogie.models import (
    AffectationEnseignant, ChoixQuestion, Matiere, MatiereNiveau, QuestionQuiz, TentativeQuiz,
)
from applications.academique.services import creer_niveau
from applications.apprenants.models import Inscription
from applications.noyau.models import Utilisateur


class TestsPedagogie(TestCase):
    def setUp(self):
        self.m = monde_scolaire()

    def test_bareme_differents_selon_le_niveau(self):
        for niveau, bareme in ((self.m["n8"], 100), ):
            services.definir_matiere_niveau(self.m["annee"], niveau, self.m["maths"], bareme)
        n9 = creer_niveau(self.m["etab"], "9e année")
        mn9 = services.definir_matiere_niveau(self.m["annee"], n9, self.m["maths"], 200)
        self.assertEqual(mn9.bareme, 200)
        self.assertEqual(self.m["mn"].bareme, 100)

    def test_classes_d_un_meme_niveau_heritent_sans_configuration(self):
        for classe in (self.m["classe_a"], self.m["classe_b"]):
            self.assertEqual(list(services.matieres_de_classe(classe)), [self.m["mn"]])
            self.assertEqual(services.bareme_applique(self.m["mn"], classe), 100)

    def test_derogation_explicite(self):
        services.definir_derogation(self.m["classe_b"], self.m["mn"], bareme=150)
        self.assertEqual(services.bareme_applique(self.m["mn"], self.m["classe_b"]), 150)
        self.assertEqual(services.bareme_applique(self.m["mn"], self.m["classe_a"]), 100)
        services.definir_derogation(self.m["classe_b"], self.m["mn"], exclue=True)
        self.assertEqual(list(services.matieres_de_classe(self.m["classe_b"])), [])

    def test_bareme_invalide(self):
        with self.assertRaises(ErreurMetier):
            services.definir_matiere_niveau(self.m["annee"], self.m["n8"], self.m["maths"], 0)

    def test_matiere_en_double_refusee(self):
        with self.assertRaises(ErreurMetier):
            services.creer_matiere(self.m["etab"], "mathématiques")

    def test_module_professionnel_peut_etre_ajoute_au_referentiel_sans_niveau(self):
        professionnel = creer_etablissement("Centre professionnel", TypeEtablissement.PROFESSIONNEL)
        utilisateur = self.m["directeur"].utilisateur
        Appartenance.sans_filtre.create(
            utilisateur=utilisateur,
            etablissement=professionnel,
            role=Role.sans_filtre.get(etablissement=professionnel, nom="Administrateur de l'établissement"),
        )
        self.client.force_login(utilisateur)
        self.client.session["etablissement_id"] = professionnel.pk
        self.client.session.save()

        page = self.client.get(reverse("pedagogie:matieres"))
        self.assertContains(page, "Nom : Module pratique")
        self.assertContains(page, "sans choisir de niveau")
        self.assertContains(page, '<form method="post" novalidate>', html=False)

        reponse = self.client.post(reverse("pedagogie:matieres"), {"nom": "Électricité résidentielle"})

        self.assertRedirects(reponse, reverse("pedagogie:matieres"), fetch_redirect_response=False)
        module = Matiere.sans_filtre.get(etablissement=professionnel, nom="Électricité résidentielle")
        self.assertFalse(MatiereNiveau.sans_filtre.filter(matiere=module).exists())

    def test_seul_un_enseignant_peut_etre_affecte(self):
        with self.assertRaises(ErreurMetier):
            services.affecter_enseignant(self.m["secretaire"], self.m["mn"], self.m["classe_b"])
        with self.assertRaises(ErreurMetier):
            services.affecter_enseignant(self.m["prof"], self.m["mn"], self.m["classe_a"])  # déjà affecté

    def test_affectation_inter_etablissements_refusee(self):
        autre = monde_scolaire("Autre")
        with self.assertRaises(ErreurMetier):
            services.affecter_enseignant(autre["prof"], self.m["mn"], self.m["classe_b"])
        with self.assertRaises(ErreurMetier):
            services.affecter_enseignant(self.m["prof"], self.m["mn"], autre["classe_a"])
        with self.assertRaises(ValidationError):
            AffectationEnseignant(
                etablissement=self.m["etab"], appartenance=self.m["prof"],
                matiere_niveau=self.m["mn"], classe=autre["classe_a"],
            ).full_clean()

    def test_affectation_doublon_refuse_a_la_sauvegarde_du_modele(self):
        with self.assertRaises(ValidationError):
            AffectationEnseignant.sans_filtre.create(
                etablissement=self.m["etab"], appartenance=self.m["prof"],
                matiere_niveau=self.m["mn"], classe=self.m["classe_a"],
            )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    @mock.patch("applications.noyau.saas.send_mail", return_value=1)
    def test_invitation_enseignant_depuis_le_formulaire_affectation(self, envoyer):
        responsable = creer_membre(
            self.m["etab"], "rp_invitation", "rp_invitation@ecole.test", "MotDePasse!2026",
            "Responsable pédagogique",
        )
        self.client.force_login(responsable.utilisateur)
        page = self.client.get(reverse("pedagogie:affectations"))
        self.assertContains(page, 'data-bs-target="#modalInvitationEnseignant"')
        self.assertContains(page, "Inviter un enseignant")

        page = self.client.post(
            reverse("pedagogie:inviter_enseignant"), {"email": "nouvel.enseignant@ecole.test"}, follow=True
        )
        invitation = Invitation.sans_filtre.get(email="nouvel.enseignant@ecole.test")
        self.assertEqual(invitation.role.nom, "Enseignant")
        self.assertContains(page, "aucun e-mail n’a été livré")
        envoyer.assert_called_once()

    def test_invitation_enseignant_refusee_sans_permission_pedagogique(self):
        self.client.force_login(self.m["prof"].utilisateur)
        reponse = self.client.post(
            reverse("pedagogie:inviter_enseignant"), {"email": "nouvel.enseignant@ecole.test"}
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Invitation.sans_filtre.filter(email="nouvel.enseignant@ecole.test").exists())

    def creer_quiz(self, **options):
        return services.creer_quiz(
            self.m["etab"], self.m["prof"], self.m["classe_a"], self.m["mn"],
            "Quiz de calcul", "", [{"texte": "2 + 2 ?", "choix": ["3", "4"], "bonne_reponse": 1}],
            **options,
        )

    def test_quiz_est_corrige_automatiquement_et_limite_en_tentatives(self):
        quiz = self.creer_quiz(nombre_tentatives_max=1)
        inscription = inscrire(self.m, "Quiz")
        question = QuestionQuiz.objects.get(quiz=quiz)
        bonne_reponse = ChoixQuestion.objects.get(question=question, correct=True)

        tentative = services.soumettre_quiz(
            quiz, inscription, {str(question.pk): str(bonne_reponse.pk)}, self.m["prof"].utilisateur
        )

        self.assertEqual(tentative.score, 1)
        self.assertEqual(tentative.reponses.count(), 1)
        with self.assertRaises(ErreurMetier):
            services.soumettre_quiz(
                quiz, inscription, {str(question.pk): str(bonne_reponse.pk)}, self.m["prof"].utilisateur
            )

    def test_apprenant_peut_soumettre_un_quiz_sans_exposer_la_correction(self):
        quiz = self.creer_quiz()
        inscription = inscrire(self.m, "Apprenant quiz")
        utilisateur = Utilisateur.objects.create_user(
            "apprenantquiz", "apprenant.quiz@example.test", "MotDePasse!2026"
        )
        inscription.apprenant.utilisateur = utilisateur
        inscription.apprenant.save(update_fields=["utilisateur"])
        from applications.noyau.models import Appartenance, Role

        Appartenance.sans_filtre.create(
            etablissement=self.m["etab"], utilisateur=utilisateur,
            role=Role.sans_filtre.get(etablissement=self.m["etab"], nom="Apprenant"),
        )
        self.client.force_login(utilisateur)

        page = self.client.get(reverse("pedagogie:quiz_detail", args=[quiz.pk]))

        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'correct="True"')
        question = QuestionQuiz.objects.get(quiz=quiz)
        choix = question.choix.order_by("ordre").last()
        reponse = self.client.post(
            reverse("pedagogie:quiz_detail", args=[quiz.pk]), {f"question_{question.pk}": choix.pk}
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(TentativeQuiz.objects.get().score, 1)
