from decimal import Decimal
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.urls import reverse

from applications.academique import services as academique
from applications.evaluations import services
from applications.evaluations.models import DocumentResultat, HistoriqueNote, Note, ResultatPeriode
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Utilisateur
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.pedagogie import services as pedagogie


class BaseEvaluations(TestCase):
    def setUp(self):
        self.m = monde_scolaire()
        academique.ouvrir_periode(self.m["periode1"])
        self.config = services.creer_configuration(self.m["affectation"], self.m["periode1"])
        self.prof = self.m["prof"]
        self.ins1 = inscrire(self.m, "Alpha")
        self.ins2 = inscrire(self.m, "Beta")

    def configurer(self, composantes=((("Interrogation", 10)), ("Devoir", 20), ("Examen", 70))):
        services.definir_composantes(self.config, composantes)
        services.valider_configuration(self.config)
        self.config.refresh_from_db()
        return {c.intitule: c for c in self.config.composantes.all()}

    def saisie(self, inscription, composante, valeur, etat="SAISIE"):
        return {"inscription_id": inscription.pk, "composante_id": composante.pk, "valeur": valeur, "etat": etat}


class TestsConfiguration(BaseEvaluations):
    def test_deux_organisations_differentes_sans_changer_le_modele(self):
        self.configurer()  # 10 + 20 + 70 = 100
        p2 = self.m["annee"].periodes.get(ordre=2)
        config2 = services.creer_configuration(self.m["affectation"], p2)
        services.definir_composantes(config2, [("Examen sur table", 100)])
        services.valider_configuration(config2)
        self.assertEqual(config2.composantes.count(), 1)

    def test_somme_differente_du_bareme_bloque_la_validation(self):
        services.definir_composantes(self.config, [("Devoir", 20), ("Examen", 60)])
        with self.assertRaises(ErreurMetier) as ctx:
            services.valider_configuration(self.config)
        self.assertIn("80", str(ctx.exception))
        self.assertIn("il manque 20", str(ctx.exception))
        self.config.refresh_from_db()
        self.assertEqual(self.config.statut, "BROUILLON")

    def test_somme_trop_elevee(self):
        services.definir_composantes(self.config, [("Examen", 120)])
        with self.assertRaises(ErreurMetier) as ctx:
            services.valider_configuration(self.config)
        self.assertIn("en trop", str(ctx.exception))

    def test_composante_invalide(self):
        with self.assertRaises(ErreurMetier):
            services.definir_composantes(self.config, [("", 10)])
        with self.assertRaises(ErreurMetier):
            services.definir_composantes(self.config, [("X", 0)])
        with self.assertRaises(ErreurMetier):
            services.definir_composantes(self.config, [])

    def test_bareme_derogatoire_pris_en_compte(self):
        services_ped = pedagogie
        services_ped.definir_derogation(self.m["classe_a"], self.m["mn"], bareme=50)
        services.definir_composantes(self.config, [("Examen", 50)])
        services.valider_configuration(self.config)

    def test_configuration_validee_non_modifiable_sans_reouverture(self):
        self.configurer()
        with self.assertRaises(ErreurMetier):
            services.definir_composantes(self.config, [("Examen", 100)])
        with self.assertRaises(ErreurMetier):
            services.rouvrir_configuration(self.config, "")
        services.rouvrir_configuration(self.config, "Erreur de barème")
        services.definir_composantes(self.config, [("Examen", 100)])

    def test_bareme_de_matiere_gele_apres_validation(self):
        self.configurer()
        with self.assertRaises(ErreurMetier):
            pedagogie.definir_matiere_niveau(self.m["annee"], self.m["n7"], self.m["maths"], 200)


class TestsSaisieEtResultats(BaseEvaluations):
    def test_historique_immutabile_cree_a_la_saisie_et_a_la_correction(self):
        composantes = self.configurer([("Examen", 100)])
        examen = composantes["Examen"]
        services.saisir_notes(self.config, [self.saisie(self.ins1, examen, "72")], self.prof)
        services.saisir_notes(
            self.config, [self.saisie(self.ins1, examen, "84")], self.prof, motif="Correction après vérification"
        )

        historique = list(HistoriqueNote.objects.filter(inscription=self.ins1).order_by("date_modification"))
        self.assertEqual(len(historique), 2)
        self.assertIsNone(historique[0].ancienne_valeur)
        self.assertEqual(historique[0].nouvelle_valeur, Decimal("72"))
        self.assertEqual(historique[1].ancienne_valeur, Decimal("72"))
        self.assertEqual(historique[1].nouvelle_valeur, Decimal("84"))
        self.assertEqual(historique[1].motif, "Correction après vérification")

    def test_superutilisateur_sans_appartenance_est_refuse_sur_les_evaluations(self):
        superutilisateur = Utilisateur.objects.create_superuser(
            "super_plateforme", "super@exemple.test", "MotDePasse!2026"
        )
        self.client.force_login(superutilisateur)
        session = self.client.session
        session["etablissement_id"] = self.m["etab"].pk
        session.save()

        reponse = self.client.get(reverse("evaluations:mes_evaluations"))

        self.assertEqual(reponse.status_code, 403)

    def test_page_saisie_affiche_un_champ_vide_sans_note_existante(self):
        composantes = self.configurer([("Examen", 100)])
        self.client.force_login(self.prof.utilisateur)

        reponse = self.client.get(reverse("evaluations:saisie", args=[self.config.pk]))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, f'name="note_{self.ins1.pk}_{composantes["Examen"].pk}" inputmode="decimal" value=""')

    def test_saisie_refusee_si_configuration_non_validee(self):
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [], self.prof)

    def test_saisie_et_calcul(self):
        c = self.configurer()
        services.saisir_notes(self.config, [
            self.saisie(self.ins1, c["Interrogation"], "8"), self.saisie(self.ins1, c["Devoir"], "15,5"),
            self.saisie(self.ins1, c["Examen"], "40"),
            self.saisie(self.ins2, c["Interrogation"], "2"), self.saisie(self.ins2, c["Devoir"], "5"),
            self.saisie(self.ins2, c["Examen"], "20"),
        ], self.prof)
        r1 = ResultatPeriode.objects.get(inscription=self.ins1)
        r2 = ResultatPeriode.objects.get(inscription=self.ins2)
        self.assertEqual(r1.total, Decimal("63.50"))
        self.assertEqual(r1.statut, "REUSSI")
        self.assertEqual(r2.pourcentage, Decimal("27.00"))
        self.assertEqual(r2.statut, "ECHEC")

    def test_reussite_a_exactement_la_moitie(self):
        c = self.configurer()
        services.saisir_notes(self.config, [
            self.saisie(self.ins1, c["Interrogation"], "5"), self.saisie(self.ins1, c["Devoir"], "10"),
            self.saisie(self.ins1, c["Examen"], "35"),
        ], self.prof)
        self.assertEqual(ResultatPeriode.objects.get(inscription=self.ins1).statut, "REUSSI")

    def test_note_hors_bareme_refusee(self):
        c = self.configurer()
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(self.ins1, c["Interrogation"], "11")], self.prof)
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(self.ins1, c["Interrogation"], "-1")], self.prof)
        self.assertEqual(Note.objects.count(), 0)  # transaction atomique

    def test_absent_n_est_pas_un_zero(self):
        c = self.configurer()
        services.saisir_notes(self.config, [
            self.saisie(self.ins1, c["Interrogation"], "10"), self.saisie(self.ins1, c["Devoir"], "20"),
            self.saisie(self.ins1, c["Examen"], None, "ABSENT"),
        ], self.prof)
        resultat = ResultatPeriode.objects.get(inscription=self.ins1)
        self.assertEqual(resultat.statut, "INCOMPLET")
        self.assertIsNone(resultat.pourcentage)
        note = Note.objects.get(inscription=self.ins1, composante=c["Examen"])
        self.assertIsNone(note.valeur)

    def test_dispense_renormalise_le_bareme(self):
        c = self.configurer()
        services.saisir_notes(self.config, [
            self.saisie(self.ins1, c["Interrogation"], None, "DISPENSE"),
            self.saisie(self.ins1, c["Devoir"], "20"), self.saisie(self.ins1, c["Examen"], "35"),
        ], self.prof)
        resultat = ResultatPeriode.objects.get(inscription=self.ins1)
        self.assertEqual(resultat.bareme_applique, 90)
        self.assertEqual(resultat.pourcentage, Decimal("61.11"))

    def test_apprenant_non_saisi_est_incomplet(self):
        self.configurer()
        services.calculer_resultats(self.config)
        self.assertEqual(ResultatPeriode.objects.filter(statut="INCOMPLET").count(), 2)

    def test_seul_l_enseignant_affecte_peut_saisir(self):
        c = self.configurer()
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(self.ins1, c["Examen"], "10")], self.m["secretaire"])

    def test_apprenant_d_une_autre_classe_hors_perimetre(self):
        c = self.configurer()
        autre = inscrire(self.m, "Gamma", classe=self.m["classe_b"])
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(autre, c["Examen"], "10")], self.prof)

    def test_inscription_non_validee_hors_perimetre(self):
        c = self.configurer()
        en_attente = inscrire(self.m, "Delta", valider=False)
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(en_attente, c["Examen"], "10")], self.prof)

    def test_filtre_par_composante_respecte_la_classe_affectee(self):
        services.definir_composantes(self.config, [("Examen classe A", 100)])
        services.valider_configuration(self.config)
        composante_a = self.config.composantes.get()
        services.calculer_resultats(self.config)

        inscription_b = inscrire(self.m, "Epsilon", classe=self.m["classe_b"])
        affectation_b = pedagogie.affecter_enseignant(self.prof, self.m["mn"], self.m["classe_b"])
        configuration_b = services.creer_configuration(affectation_b, self.m["periode1"])
        services.definir_composantes(configuration_b, [("Oral classe B", 100)])
        services.valider_configuration(configuration_b)
        composante_b = configuration_b.composantes.get()
        services.calculer_resultats(configuration_b)

        resultats_a = services.resultats_visibles(
            self.prof.utilisateur, self.prof, {"composante": str(composante_a.pk)}
        )
        resultats_b = services.resultats_visibles(
            self.prof.utilisateur, self.prof, {"composante": str(composante_b.pk)}
        )
        self.assertEqual(set(resultats_a.values_list("inscription_id", flat=True)), {self.ins1.pk, self.ins2.pk})
        self.assertEqual(set(resultats_b.values_list("inscription_id", flat=True)), {inscription_b.pk})

    def test_saisie_fermee_avec_la_periode(self):
        c = self.configurer()
        academique.basculer_saisie(self.m["periode1"], False)
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(self.ins1, c["Examen"], "10")], self.prof)

    def test_modification_tracee(self):
        from applications.noyau.models import JournalAudit

        c = self.configurer()
        services.saisir_notes(self.config, [self.saisie(self.ins1, c["Examen"], "30")], self.prof)
        services.saisir_notes(self.config, [self.saisie(self.ins1, c["Examen"], "45")], self.prof)
        ligne = JournalAudit.objects.get(action="note.modification")
        self.assertEqual(ligne.avant["valeur"], "30.00")
        self.assertEqual(ligne.apres["valeur"], "45")


class TestsPublication(BaseEvaluations):
    def remplir(self, c, ins, valeurs=(10, 20, 70)):
        services.saisir_notes(self.config, [
            self.saisie(ins, c["Interrogation"], str(valeurs[0])), self.saisie(ins, c["Devoir"], str(valeurs[1])),
            self.saisie(ins, c["Examen"], str(valeurs[2])),
        ], self.prof)

    def test_publication_refusee_si_incomplets(self):
        c = self.configurer()
        self.remplir(c, self.ins1)
        with self.assertRaises(ErreurMetier):
            services.publier_resultats(self.config, self.m["directeur"].utilisateur)

    def test_publication_et_correction_avec_motif(self):
        c = self.configurer()
        self.remplir(c, self.ins1)
        self.remplir(c, self.ins2, (1, 1, 1))
        publies, incomplets = services.publier_resultats(self.config, self.m["directeur"].utilisateur)
        self.assertEqual((publies, incomplets), (2, 0))
        with self.assertRaises(ErreurMetier):
            services.saisir_notes(self.config, [self.saisie(self.ins2, c["Examen"], "60")], self.prof)
        services.saisir_notes(self.config, [self.saisie(self.ins2, c["Examen"], "60")], self.prof, motif="Erreur de saisie")
        self.assertEqual(ResultatPeriode.objects.get(inscription=self.ins2).statut, "REUSSI")
        with self.assertRaises(ErreurMetier):
            services.rouvrir_configuration(self.config, "test")
        self.assertEqual(services.depublier_resultats(self.config, self.m["directeur"].utilisateur, "Contrôle"), 2)

    def test_document_pdf_versionne_et_revoque_apres_correction(self):
        composantes = self.configurer()
        self.remplir(composantes, self.ins1)
        self.remplir(composantes, self.ins2)
        services.publier_resultats(self.config, self.m["directeur"].utilisateur)
        self.client.force_login(self.m["directeur"].utilisateur)

        with TemporaryDirectory() as dossier_prive, override_settings(PRIVATE_MEDIA_ROOT=dossier_prive):
            page = self.client.get(reverse("evaluations:resultats"), {
                "vue": "bulletin", "periode": self.m["periode1"].pk,
            })
            self.assertContains(page, "Émettre le PDF")
            creation = reverse(
                "evaluations:document_creer", args=[self.ins1.pk, self.m["periode1"].pk]
            )
            self.assertEqual(self.client.post(creation).status_code, 302)
            document = DocumentResultat.objects.get(inscription=self.ins1)
            self.assertEqual(document.version, 1)

            telechargement = reverse("evaluations:document_telecharger", args=[document.pk])
            reponse = self.client.get(telechargement)
            self.assertEqual(reponse.status_code, 200)
            self.assertTrue(b"".join(reponse.streaming_content).startswith(b"%PDF"))
            reponse.close()

            services.saisir_notes(
                self.config,
                [self.saisie(self.ins1, composantes["Examen"], "60")],
                self.prof,
                motif="Correction après vérification",
            )
            document.refresh_from_db()
            self.assertIsNotNone(document.revoque_le)
            self.assertEqual(self.client.get(telechargement).status_code, 404)

            self.assertEqual(self.client.post(creation).status_code, 302)
            version_suivante = DocumentResultat.objects.get(inscription=self.ins1, version=2)
            self.assertIsNone(version_suivante.revoque_le)
            reponse = self.client.get(
                reverse("evaluations:document_telecharger", args=[version_suivante.pk])
            )
            self.assertEqual(reponse.status_code, 200)
            self.assertTrue(b"".join(reponse.streaming_content).startswith(b"%PDF"))
            reponse.close()

            revocation = reverse("evaluations:document_revoquer", args=[version_suivante.pk])
            self.client.post(revocation, {"motif": ""})
            version_suivante.refresh_from_db()
            self.assertIsNone(version_suivante.revoque_le)
            self.client.post(revocation, {"motif": "Erreur de publication"})
            version_suivante.refresh_from_db()
            self.assertIsNotNone(version_suivante.revoque_le)
            self.assertEqual(self.client.get(
                reverse("evaluations:document_telecharger", args=[version_suivante.pk])
            ).status_code, 404)

    def test_statistiques_et_classement(self):
        c = self.configurer()
        self.remplir(c, self.ins1, (10, 20, 70))
        self.remplir(c, self.ins2, (1, 1, 10))
        stats = services.statistiques_configuration(self.config)
        self.assertEqual(stats["taux_reussite"], Decimal("50.00"))
        self.assertEqual(stats["moyenne_pct"], Decimal("56.00"))
        self.assertEqual(len(stats["en_difficulte"]), 1)
        self.assertEqual(stats["classement"], [])  # classement non autorisé par défaut
        self.m["etab"].parametres.classement_autorise = True
        self.m["etab"].parametres.save()
        self.assertEqual(services.statistiques_configuration(self.config)["classement"][0].inscription, self.ins1)

    def test_moyenne_generale_ponderee_et_echelle_configurable(self):
        c = self.configurer()
        self.remplir(c, self.ins1, (10, 20, 70))  # 100 %
        physique = pedagogie.creer_matiere(self.m["etab"], "Physique")
        mn2 = pedagogie.definir_matiere_niveau(self.m["annee"], self.m["n7"], physique, 20, coefficient=2)
        aff2 = pedagogie.affecter_enseignant(self.m["prof"], mn2, self.m["classe_a"])
        cfg2 = services.creer_configuration(aff2, self.m["periode1"])
        services.definir_composantes(cfg2, [("Examen", 20)])
        services.valider_configuration(cfg2)
        services.saisir_notes(cfg2, [{"inscription_id": self.ins1.pk, "composante_id": cfg2.composantes.get().pk,
                                      "valeur": "10", "etat": "SAISIE"}], self.prof)  # 50 %, coefficient 2
        resultat = services.moyenne_generale(self.ins1, self.m["periode1"])
        self.assertEqual(resultat["pourcentage"], Decimal("66.67"))
        self.assertEqual(resultat["moyenne"], Decimal("13.33"))  # échelle 20 par défaut
        parametres = self.m["etab"].parametres
        parametres.echelle_moyenne = 10
        parametres.save()
        self.assertEqual(services.moyenne_generale(self.ins1, self.m["periode1"])["moyenne"], Decimal("6.67"))

    def test_rang_par_matiere_et_bulletin_synthetique_consolide(self):
        config_maths = self.configurer()
        self.remplir(config_maths, self.ins1, (10, 20, 50))
        self.remplir(config_maths, self.ins2, (10, 20, 30))
        services.publier_resultats(self.config, self.m["directeur"].utilisateur)

        physique = pedagogie.creer_matiere(self.m["etab"], "Physique")
        matiere_niveau_physique = pedagogie.definir_matiere_niveau(
            self.m["annee"], self.m["n7"], physique, 100
        )
        affectation_physique = pedagogie.affecter_enseignant(
            self.prof, matiere_niveau_physique, self.m["classe_a"]
        )
        config_physique = services.creer_configuration(affectation_physique, self.m["periode1"])
        services.definir_composantes(config_physique, [("Examen", 100)])
        services.valider_configuration(config_physique)
        services.saisir_notes(config_physique, [
            self.saisie(self.ins1, config_physique.composantes.get(), "30"),
            self.saisie(self.ins2, config_physique.composantes.get(), "90"),
        ], self.prof)
        services.publier_resultats(config_physique, self.m["directeur"].utilisateur)

        rangs = services.rangs_par_resultat(ResultatPeriode.objects.filter(
            periode=self.m["periode1"], matiere_niveau=self.m["mn"]
        ))
        self.assertEqual(rangs[ResultatPeriode.objects.get(inscription=self.ins1, matiere_niveau=self.m["mn"]).pk], 1)
        self.assertEqual(rangs[ResultatPeriode.objects.get(inscription=self.ins2, matiere_niveau=self.m["mn"]).pk], 2)

        self.m["etab"].parametres.classement_autorise = True
        self.m["etab"].parametres.save(update_fields=["classement_autorise"])
        bulletins = services.bulletins_synthetiques(self.m["periode1"])
        par_inscription = {bulletin["inscription"].pk: bulletin for bulletin in bulletins}
        self.assertTrue(par_inscription[self.ins1.pk]["complet"])
        self.assertTrue(par_inscription[self.ins2.pk]["complet"])
        self.assertEqual(par_inscription[self.ins1.pk]["moyenne"]["moyenne"], Decimal("11.00"))
        self.assertEqual(par_inscription[self.ins1.pk]["moyenne"]["total_points"], Decimal("110.00"))
        self.assertEqual(par_inscription[self.ins1.pk]["moyenne"]["bareme_total"], Decimal("200.00"))
        self.assertEqual(par_inscription[self.ins1.pk]["rang"], 2)
        self.assertEqual(par_inscription[self.ins2.pk]["moyenne"]["moyenne"], Decimal("15.00"))
        self.assertEqual(par_inscription[self.ins2.pk]["rang"], 1)

        self.client.force_login(self.m["directeur"].utilisateur)
        reponse = self.client.get(reverse("evaluations:resultats"), {
            "vue": "bulletin", "periode": self.m["periode1"].pk,
        })
        self.assertContains(reponse, "Moyenne générale")
        self.assertContains(reponse, "Total général")
        self.assertContains(reponse, "Bulletin synthétique")
        self.assertContains(reponse, "Physique")
        self.assertContains(reponse, "1er")
        self.assertContains(reponse, "2e")
        bulletins_par_inscription = {
            bulletin["inscription"].pk: bulletin for bulletin in reponse.context["bulletins"]
        }
        self.assertEqual(
            bulletins_par_inscription[self.ins1.pk]["notes_matieres"][self.m["mn"].matiere_id]["total"],
            ResultatPeriode.objects.get(inscription=self.ins1, matiere_niveau=self.m["mn"]).total,
        )
        self.assertEqual(
            bulletins_par_inscription[self.ins1.pk]["notes_matieres"][physique.pk]["total"],
            ResultatPeriode.objects.get(inscription=self.ins1, matiere_niveau__matiere=physique).total,
        )
        self.assertEqual(
            bulletins_par_inscription[self.ins1.pk]["notes_matieres"][physique.pk]["bareme"],
            ResultatPeriode.objects.get(inscription=self.ins1, matiere_niveau__matiere=physique).bareme_applique,
        )
        self.assertEqual(
            reponse.context["baremes_bulletin"][physique.pk],
            ResultatPeriode.objects.get(inscription=self.ins1, matiere_niveau__matiere=physique).bareme_applique,
        )

    def test_seuil_de_reussite_configurable(self):
        parametres = self.m["etab"].parametres
        parametres.seuil_reussite_pct = 60
        parametres.save()
        c = self.configurer()
        self.remplir(c, self.ins1, (5, 10, 40))  # 55 %
        self.assertEqual(ResultatPeriode.objects.get(inscription=self.ins1).statut, "ECHEC")

    def test_visibilite_des_resultats_par_role(self):
        c = self.configurer()
        self.remplir(c, self.ins1)
        autre_prof = __import__("applications.noyau.services", fromlist=["x"]).creer_membre(
            self.m["etab"], "prof2", "prof2@x.test", "MotDePasse!2026", "Enseignant")
        self.assertEqual(services.resultats_visibles(self.prof.utilisateur, self.prof).count(), 2)
        self.assertEqual(services.resultats_visibles(autre_prof.utilisateur, autre_prof).count(), 0)
        d = self.m["directeur"]
        self.assertEqual(services.resultats_visibles(d.utilisateur, d).count(), 2)
        self.assertEqual(services.resultats_visibles(self.m["secretaire"].utilisateur, self.m["secretaire"]).count(), 0)

    def test_portail_apprenant_ne_voit_que_ses_resultats_publies(self):
        c = self.configurer()
        self.remplir(c, self.ins1)
        self.remplir(c, self.ins2)
        compte = __import__("applications.noyau.services", fromlist=["x"]).creer_membre(
            self.m["etab"], "eleve1", "eleve1@x.test", "MotDePasse!2026", "Apprenant")
        self.ins1.apprenant.utilisateur = compte.utilisateur
        self.ins1.apprenant.save()
        self.assertEqual(services.resultats_portail(compte.utilisateur).count(), 0)  # non publiés
        services.publier_resultats(self.config, self.m["directeur"].utilisateur)
        visibles = services.resultats_portail(compte.utilisateur)
        self.assertEqual({r.inscription.apprenant_id for r in visibles}, {self.ins1.apprenant_id})

        with TemporaryDirectory() as dossier_prive, override_settings(PRIVATE_MEDIA_ROOT=dossier_prive):
            document = services.generer_document_resultat(
                self.ins1, self.m["periode1"], self.m["directeur"].utilisateur
            )
            document_autre_apprenant = services.generer_document_resultat(
                self.ins2, self.m["periode1"], self.m["directeur"].utilisateur
            )
            self.client.force_login(compte.utilisateur)
            portail = self.client.get(reverse("evaluations:portail"))
            self.assertContains(portail, "Télécharger")
            telechargement = self.client.get(
                reverse("evaluations:document_telecharger", args=[document.pk])
            )
            self.assertEqual(telechargement.status_code, 200)
            telechargement.close()
            self.assertEqual(self.client.get(
                reverse("evaluations:document_telecharger", args=[document_autre_apprenant.pk])
            ).status_code, 403)
