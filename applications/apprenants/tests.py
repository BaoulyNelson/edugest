from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from applications.academique import services as academique
from applications.apprenants import services
from applications.apprenants.forms import FormulaireApprenant
from applications.apprenants.models import Apprenant, DecisionInscription, Inscription
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import JournalAudit
from applications.noyau.outils_tests import inscrire, monde_scolaire, monde_universitaire


class TestsInscriptions(TestCase):
    def setUp(self):
        self.m = monde_scolaire()

    def nouvel_apprenant(self, nom="Dupont"):
        return services.creer_apprenant(self.m["etab"], nom, "Jean", "M", date(2013, 1, 1))

    def test_matricule_automatique_et_unique(self):
        a, b = self.nouvel_apprenant("A"), self.nouvel_apprenant("B")
        self.assertNotEqual(a.matricule, b.matricule)
        self.assertRegex(a.matricule, r"^\d{4}-\d{5}$")

    def test_modifier_apprenant_met_a_jour_la_fiche_et_trace_la_correction(self):
        apprenant = self.nouvel_apprenant()
        services.modifier_apprenant(
            apprenant, par=self.m["directeur"].utilisateur,
            nom="Martin", prenoms="Jeanne", sexe="F", date_naissance=date(2013, 2, 1),
            lieu_naissance="Cap-Haïtien", email="jeanne@example.test",
            telephone="50912345678", adresse="Rue 1",
        )
        apprenant.refresh_from_db()
        self.assertEqual((apprenant.nom, apprenant.prenoms, apprenant.email), (
            "MARTIN", "Jeanne", "jeanne@example.test",
        ))
        self.assertTrue(JournalAudit.objects.filter(
            action="apprenant.modification", objet_id=str(apprenant.pk),
        ).exists())

    def test_modifier_responsable_principal_est_inclus_dans_l_audit(self):
        responsable = services.creer_responsable(self.m["etab"], "Jean", "Parent")
        apprenant = services.creer_apprenant(
            self.m["etab"], "Élève", "Test", "M", date(2013, 1, 1), responsable=responsable
        )
        services.modifier_apprenant(
            apprenant, par=self.m["directeur"].utilisateur,
            nom="Élève", prenoms="Test", sexe="M", date_naissance=date(2013, 1, 1),
            lieu_naissance="", email="", telephone="", adresse="",
            responsable_nom="Jean corrigé", responsable_prenoms="Parent",
            responsable_telephone="", responsable_email="", responsable_lien="TUTEUR",
        )
        journal = JournalAudit.objects.get(
            action="apprenant.modification", objet_id=str(apprenant.pk),
        )
        self.assertEqual(journal.avant["responsable"]["nom"], "Jean")
        self.assertEqual(journal.apres["responsable"]["nom"], "Jean corrigé")

    def test_modifier_apprenant_depuis_le_dossier(self):
        apprenant = self.nouvel_apprenant()
        self.client.force_login(self.m["secretaire"].utilisateur)
        url = reverse("apprenants:modifier", args=[apprenant.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        reponse = self.client.post(url, {
            "nom": "Corrige", "prenoms": "Jean", "sexe": "M",
            "date_naissance": "2013-01-01", "lieu_naissance": "",
            "email": "corrige@example.test", "telephone": "", "adresse": "",
            "responsable_nom": "", "responsable_prenoms": "",
            "responsable_telephone": "", "responsable_email": "", "responsable_lien": "TUTEUR",
        })
        self.assertRedirects(
            reponse, reverse("apprenants:detail", args=[apprenant.pk]),
            fetch_redirect_response=False,
        )
        apprenant.refresh_from_db()
        self.assertEqual(apprenant.nom, "CORRIGE")
        self.assertEqual(apprenant.email, "corrige@example.test")

    def test_dossier_anonymise_non_modifiable(self):
        apprenant = self.nouvel_apprenant()
        apprenant.anonymise = True
        apprenant.save(update_fields=["anonymise"])
        with self.assertRaises(ErreurMetier):
            services.modifier_apprenant(
                apprenant, nom="Corrige", prenoms="Jean", sexe="M",
                date_naissance=date(2013, 1, 1), lieu_naissance="",
                email="", telephone="", adresse="",
            )

    def test_date_de_naissance_future_refusee_et_date_du_jour_acceptee(self):
        aujourd_hui = timezone.localdate()
        with self.assertRaises(ErreurMetier):
            services.creer_apprenant(
                self.m["etab"], "Futur", "Jean", "M", aujourd_hui + timedelta(days=1)
            )
        self.assertTrue(FormulaireApprenant({
            "nom": "Aujourd'hui", "prenoms": "Jean", "sexe": "M",
            "date_naissance": aujourd_hui.isoformat(),
        }, etablissement=self.m["etab"]).is_valid())
        self.assertFalse(FormulaireApprenant({
            "nom": "Futur", "prenoms": "Jean", "sexe": "M",
            "date_naissance": (aujourd_hui + timedelta(days=1)).isoformat(),
        }, etablissement=self.m["etab"]).is_valid())
        self.assertEqual(
            services.creer_apprenant(self.m["etab"], "Aujourd'hui", "Jean", "M", aujourd_hui).date_naissance,
            aujourd_hui,
        )

    def test_effectif_classe_verifie_a_la_creation_validation_et_changement(self):
        self.m["classe_a"].effectif_max = 1
        self.m["classe_a"].save(update_fields=["effectif_max"])
        self.m["classe_b"].effectif_max = 1
        self.m["classe_b"].save(update_fields=["effectif_max"])

        attente = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant("En attente"), self.m["n7"], self.m["classe_a"]
        )
        correction = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant("Correction"), self.m["n7"], self.m["classe_a"]
        )
        services.decider_inscription(
            correction, "DEMANDER_CORRECTION", self.m["directeur"].utilisateur, "Document manquant"
        )
        services.decider_inscription(attente, "VALIDER", self.m["directeur"].utilisateur)
        attente.refresh_from_db()
        with self.assertRaises(ErreurMetier):
            services.decider_inscription(correction, "VALIDER", self.m["directeur"].utilisateur)
        correction.refresh_from_db()
        self.assertEqual(correction.statut, Inscription.Statut.CORRECTION_DEMANDEE)
        with self.assertRaises(ErreurMetier):
            services.creer_inscription(
                self.m["etab"], self.nouvel_apprenant("Nouvelle"), self.m["n7"], self.m["classe_a"]
            )

        autre = inscrire(self.m, "Déjà dans B", self.m["classe_b"])
        with self.assertRaises(ErreurMetier):
            services.changer_classe(attente, self.m["classe_b"])
        services.changer_classe(attente, self.m["classe_a"])
        self.assertEqual(autre.classe, self.m["classe_b"])

    def test_modele_apprenant_refuse_une_date_future(self):
        apprenant = Apprenant(
            etablissement=self.m["etab"], matricule="TEST", nom="Futur", prenoms="Jean",
            sexe="M", date_naissance=timezone.localdate() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            apprenant.full_clean()

    def test_liste_affiche_le_sexe_de_l_apprenant(self):
        services.creer_apprenant(self.m["etab"], "Dupont", "Jeanne", "F", date(2013, 1, 1))
        self.client.force_login(self.m["directeur"].utilisateur)
        reponse = self.client.get(reverse("apprenants:liste"))
        self.assertContains(reponse, "Sexe")
        self.assertContains(reponse, "Féminin")

    def test_statut_initial_en_attente_et_non_active(self):
        ins = services.creer_inscription(self.m["etab"], self.nouvel_apprenant(), self.m["n7"], self.m["classe_a"])
        self.assertEqual(ins.statut, "EN_ATTENTE")
        self.assertFalse(ins.est_active)

    def test_modifier_inscription_en_attente_corrige_affectation_et_conserve_statut(self):
        inscription = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant(), self.m["n7"], self.m["classe_a"]
        )
        services.modifier_inscription(
            inscription, inscription.apprenant, self.m["n7"], classe=self.m["classe_b"],
            type_inscription=Inscription.Type.TRANSFERT, par=self.m["directeur"].utilisateur,
        )
        inscription.refresh_from_db()
        self.assertEqual(inscription.classe, self.m["classe_b"])
        self.assertEqual(inscription.type, Inscription.Type.TRANSFERT)
        self.assertEqual(inscription.statut, Inscription.Statut.EN_ATTENTE)

    def test_inscription_validee_avec_decision_de_passage_peut_corriger_le_niveau(self):
        inscription = inscrire(self.m, "Martin")
        inscription.decision_fin_annee = Inscription.DecisionFinAnnee.PASSAGE
        inscription.save(update_fields=["decision_fin_annee"])
        services.modifier_inscription(
            inscription, inscription.apprenant, self.m["n8"], classe=None,
            motif_correction="Erreur de saisie",
        )
        inscription.refresh_from_db()
        self.assertEqual(inscription.niveau, self.m["n8"])
        self.assertEqual(inscription.decision_fin_annee, Inscription.DecisionFinAnnee.PASSAGE)

    def test_correction_niveau_apres_validation_est_auditee_si_sans_historique_pedagogique(self):
        inscription = inscrire(self.m, "Correction")
        services.modifier_inscription(
            inscription, inscription.apprenant, self.m["n8"],
            motif_correction="Niveau mal sélectionné à la saisie",
            par=self.m["directeur"].utilisateur,
        )
        inscription.refresh_from_db()
        self.assertEqual(inscription.niveau, self.m["n8"])
        self.assertEqual(inscription.statut, Inscription.Statut.VALIDEE)
        journal = JournalAudit.objects.get(
            action="inscription.modification", objet_id=str(inscription.pk),
        )
        self.assertEqual(journal.motif, "Niveau mal sélectionné à la saisie")
        self.assertEqual(journal.avant["niveau"], str(self.m["n7"]))
        self.assertEqual(journal.apres["niveau"], str(self.m["n8"]))

    def test_correction_niveau_apres_validation_refusee_apres_saisie_de_notes(self):
        inscription = inscrire(self.m, "Avec notes")
        from applications.evaluations import services as evaluations
        from applications.evaluations.models import Note
        configuration = evaluations.creer_configuration(self.m["affectation"], self.m["periode1"])
        evaluations.definir_composantes(configuration, [("Examen", 100)])
        composante = configuration.composantes.get()
        Note.sans_filtre.create(
            etablissement=self.m["etab"], composante=composante,
            inscription=inscription, valeur=10,
        )
        with self.assertRaises(ErreurMetier):
            services.modifier_inscription(
                inscription, inscription.apprenant, self.m["n8"],
                motif_correction="Erreur de niveau",
            )

    def test_detail_indique_pourquoi_niveau_valide_est_verrouille_apres_reinscription_suivante(self):
        inscription = inscrire(self.m, "Parcours terminé")
        inscription.decision_fin_annee = Inscription.DecisionFinAnnee.PASSAGE
        inscription.save(update_fields=["decision_fin_annee"])
        academique.cloturer_annee(self.m["annee"])
        nouvelle_annee = academique.creer_annee(
            self.m["etab"], "2027-2028", date(2027, 9, 1), date(2028, 6, 30)
        )
        academique.activer_annee(nouvelle_annee)
        services.reinscrire(inscription)
        self.client.force_login(self.m["directeur"].utilisateur)
        reponse = self.client.get(reverse("apprenants:inscription_detail", args=[inscription.pk]))
        self.assertNotContains(reponse, "Corriger le niveau")
        self.assertContains(reponse, "Une inscription ultérieure est déjà en cours")

    def test_correction_niveau_valide_disponible_depuis_detail_avec_motif(self):
        inscription = inscrire(self.m, "A corriger")
        self.client.force_login(self.m["secretaire"].utilisateur)
        detail_url = reverse("apprenants:inscription_detail", args=[inscription.pk])
        self.assertContains(self.client.get(detail_url), "Corriger le niveau")
        url = reverse("apprenants:inscription_modifier", args=[inscription.pk])
        formulaire = self.client.get(url)
        self.assertContains(formulaire, "Motif de la correction")
        reponse = self.client.post(url, {
            "niveau": self.m["n8"].pk,
            "classe": "",
            "motif_correction": "Niveau sélectionné par erreur",
        })
        self.assertRedirects(reponse, detail_url, fetch_redirect_response=False)
        inscription.refresh_from_db()
        self.assertEqual(inscription.niveau_id, self.m["n8"].pk)
        self.assertEqual(inscription.statut, Inscription.Statut.VALIDEE)

    def test_modifier_inscription_depuis_le_detail(self):
        inscription = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant(), self.m["n7"], self.m["classe_a"]
        )
        self.client.force_login(self.m["secretaire"].utilisateur)
        url = reverse("apprenants:inscription_modifier", args=[inscription.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        reponse = self.client.post(url, {
            "apprenant": inscription.apprenant_id,
            "niveau": self.m["n7"].pk,
            "classe": self.m["classe_b"].pk,
            "type_inscription": Inscription.Type.TRANSFERT,
        })
        self.assertRedirects(
            reponse, reverse("apprenants:inscription_detail", args=[inscription.pk]),
            fetch_redirect_response=False,
        )
        inscription.refresh_from_db()
        self.assertEqual((inscription.classe_id, inscription.type), (
            self.m["classe_b"].pk, Inscription.Type.TRANSFERT,
        ))

    def test_inscription_impossible_sans_annee_active(self):
        academique.cloturer_annee(self.m["annee"])
        with self.assertRaises(ErreurMetier):
            services.creer_inscription(self.m["etab"], self.nouvel_apprenant(), self.m["n7"])

    def test_detail_inscription_propose_les_liens_vers_le_dossier_et_la_liste(self):
        inscription = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant(), self.m["n7"], self.m["classe_a"]
        )
        self.client.force_login(self.m["directeur"].utilisateur)
        reponse = self.client.get(reverse("apprenants:inscription_detail", args=[inscription.pk]))
        self.assertContains(reponse, reverse("apprenants:detail", args=[inscription.apprenant_id]))
        self.assertContains(reponse, "Dossier de l’élève")
        self.assertContains(reponse, reverse("apprenants:inscriptions"))
        self.assertContains(reponse, "Liste des inscriptions")

    def test_liste_filtre_les_inscriptions_a_valider_et_permet_la_validation_groupee(self):
        en_attente = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant("En attente"), self.m["n7"], self.m["classe_a"]
        )
        correction = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant("Correction"), self.m["n7"], self.m["classe_a"]
        )
        services.decider_inscription(
            correction, "DEMANDER_CORRECTION", self.m["directeur"].utilisateur, "Document manquant"
        )
        rejetee = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant("Rejetée"), self.m["n7"], self.m["classe_a"]
        )
        services.decider_inscription(
            rejetee, "REJETER", self.m["directeur"].utilisateur, "Dossier incomplet"
        )

        self.client.force_login(self.m["directeur"].utilisateur)
        page = self.client.get(reverse("apprenants:inscriptions"), {"a_valider": "1"})
        self.assertContains(page, "À valider uniquement")
        self.assertContains(page, f'value="{en_attente.pk}"')
        self.assertContains(page, f'value="{correction.pk}"')
        self.assertNotContains(page, f'value="{rejetee.pk}"')

        reponse = self.client.post(reverse("apprenants:inscriptions_valider_lot"), {
            "inscriptions": [en_attente.pk, correction.pk, rejetee.pk],
        })
        self.assertRedirects(reponse, reverse("apprenants:inscriptions"), fetch_redirect_response=False)
        en_attente.refresh_from_db()
        correction.refresh_from_db()
        rejetee.refresh_from_db()
        self.assertEqual(en_attente.statut, Inscription.Statut.VALIDEE)
        self.assertEqual(correction.statut, Inscription.Statut.VALIDEE)
        self.assertEqual(rejetee.statut, Inscription.Statut.REJETEE)

    def test_validation_groupee_est_reservee_aux_decideurs(self):
        inscription = services.creer_inscription(
            self.m["etab"], self.nouvel_apprenant(), self.m["n7"], self.m["classe_a"]
        )
        self.client.force_login(self.m["secretaire"].utilisateur)
        reponse = self.client.post(
            reverse("apprenants:inscriptions_valider_lot"),
            {"inscriptions": [inscription.pk]},
        )
        self.assertEqual(reponse.status_code, 403)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, Inscription.Statut.EN_ATTENTE)

    def test_pas_de_doublon_pour_une_meme_annee(self):
        app = self.nouvel_apprenant()
        services.creer_inscription(self.m["etab"], app, self.m["n7"])
        with self.assertRaises(ErreurMetier):
            services.creer_inscription(self.m["etab"], app, self.m["n7"])

    def test_inscription_rejetee_permet_une_nouvelle_demande(self):
        app = self.nouvel_apprenant()
        ins = services.creer_inscription(self.m["etab"], app, self.m["n7"])
        services.decider_inscription(ins, "REJETER", self.m["directeur"].utilisateur, "Pièces manquantes")
        services.creer_inscription(self.m["etab"], app, self.m["n7"])
        self.assertEqual(Inscription.objects.filter(apprenant=app).count(), 2)

    def test_decision_tracee_avec_auteur_et_motif(self):
        ins = services.creer_inscription(self.m["etab"], self.nouvel_apprenant(), self.m["n7"])
        auteur = self.m["directeur"].utilisateur
        with self.assertRaises(ErreurMetier):
            services.decider_inscription(ins, "REJETER", auteur, "")
        services.decider_inscription(ins, "DEMANDER_CORRECTION", auteur, "Acte de naissance")
        services.decider_inscription(ins, "VALIDER", auteur)
        ins.refresh_from_db()
        self.assertTrue(ins.est_active)
        decisions = DecisionInscription.objects.filter(inscription=ins)
        self.assertEqual(decisions.count(), 2)
        self.assertTrue(all(d.auteur == auteur for d in decisions))
        with self.assertRaises(ErreurMetier):
            services.decider_inscription(ins, "REJETER", auteur, "trop tard")

    def test_classe_incoherente_refusee(self):
        n8_classe = academique.creer_classe(self.m["n8"], self.m["annee"], "8e A")
        with self.assertRaises(ErreurMetier):
            services.creer_inscription(self.m["etab"], self.nouvel_apprenant(), self.m["n7"], n8_classe)

    def test_changement_de_classe(self):
        ins = inscrire(self.m, "Martin")
        services.changer_classe(ins, self.m["classe_b"])
        ins.refresh_from_db()
        self.assertEqual(ins.classe, self.m["classe_b"])

    def test_reinscription_sans_recreer_l_apprenant(self):
        ins = inscrire(self.m, "Durand")
        services.definir_decision_fin_annee(ins, "PASSAGE")
        academique.cloturer_annee(self.m["annee"])
        nouvelle = academique.creer_annee(self.m["etab"], "2027-2028", date(2027, 9, 1), date(2028, 6, 30))
        academique.activer_annee(nouvelle)
        suivante = services.reinscrire(ins)
        self.assertEqual(suivante.niveau, self.m["n8"])
        self.assertEqual(suivante.type, "REINSCRIPTION")
        self.assertEqual(suivante.apprenant_id, ins.apprenant_id)
        self.assertEqual(Apprenant.objects.count(), 1)

    def test_redoublement(self):
        ins = inscrire(self.m, "Redoublant")
        services.definir_decision_fin_annee(ins, "REDOUBLEMENT")
        academique.cloturer_annee(self.m["annee"])
        academique.activer_annee(academique.creer_annee(self.m["etab"], "2027-2028", date(2027, 9, 1), date(2028, 6, 30)))
        self.assertEqual(services.reinscrire(ins).niveau, self.m["n7"])

    def test_reinscription_sans_decision_refusee(self):
        ins = inscrire(self.m, "Sans")
        with self.assertRaises(ErreurMetier):
            services.reinscrire(ins)

    def test_apprenant_d_un_autre_etablissement_refuse(self):
        autre = monde_scolaire("Autre école")
        intrus = services.creer_apprenant(autre["etab"], "Intrus", "X", "F", date(2012, 1, 1))
        with self.assertRaises(ErreurMetier):
            services.creer_inscription(self.m["etab"], intrus, self.m["n7"])

    def test_inscription_universitaire(self):
        u = monde_universitaire()
        app = services.creer_apprenant(u["etab"], "Étudiant", "Paul", "M", date(2004, 1, 1))
        with self.assertRaises(ErreurMetier):
            services.creer_inscription(u["etab"], app, u["niveau"])  # programme manquant
        ins = services.creer_inscription(u["etab"], app, u["niveau"], programme=u["programme"])
        self.assertEqual(ins.faculte, u["faculte"])
