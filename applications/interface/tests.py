"""Tests de bout en bout par l'interface : rôles, navigation, isolation, parcours métier."""
from datetime import date, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from applications.academique import services as academique
from applications.apprenants import services as apprenants
from applications.apprenants.models import Apprenant, Inscription
from applications.evaluations import services as evaluations
from applications.evaluations.models import ResultatPeriode
from applications.finances.models import Echeance, Facture, Paiement
from applications.noyau.outils_tests import inscrire, monde_scolaire, monde_universitaire
from applications.noyau.services import creer_membre
from applications.pedagogie import services as pedagogie
from applications.pedagogie.models import Matiere
from applications.interface.terminologie import profil_etablissement
from applications.noyau.models import Appartenance, ConfigurationPlateforme, TypeEtablissement


class BaseInterface(TestCase):
    def setUp(self):
        self.m = monde_scolaire("École A")
        self.autre = monde_scolaire("École B")

    def connecter(self, appartenance):
        self.client.force_login(appartenance.utilisateur)
        return self.client


class TestsAccesEtNavigation(BaseInterface):
    def test_superadministrateur_peut_administrer_son_tenant_et_pas_un_autre(self):
        reponse = self.connecter(self.m["directeur"]).get(reverse("tableau_de_bord"))
        self.assertContains(reponse, "Élèves en activité")
        self.assertContains(reponse, "Les premiers pas")
        self.assertContains(reponse, "Confirmez votre adresse e-mail")
        self.assertNotContains(reponse, "selecteurEtablissement")

        superutilisateur = self.m["directeur"].utilisateur
        superutilisateur.is_superuser = True
        superutilisateur.email_verifie = False
        superutilisateur.save(update_fields=["is_superuser", "email_verifie"])
        reponse = self.connecter(self.m["directeur"]).get(reverse("tableau_de_bord"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Les premiers pas")
        self.assertNotContains(reponse, "selecteurEtablissement")


        self.assertNotContains(reponse, "Confirmez votre adresse e-mail")

        changement = self.client.post(reverse("choisir_etablissement_menu"), {
            "etablissement": self.autre["etab"].pk,
        })
        self.assertEqual(changement.status_code, 403)
        self.assertEqual(self.client.session["etablissement_id"], self.m["etab"].pk)
        self.assertEqual(self.client.get(reverse("academique:annees")).status_code, 200)
        self.assertEqual(self.client.get(reverse("pedagogie:matieres")).status_code, 403)
        console = self.client.get(reverse("plateforme"))
        self.assertContains(console, "Pilotage de la plateforme")
        self.assertNotContains(console, "selecteurEtablissement")

    def test_superadministrateur_peut_creer_son_tenant_et_en_devient_admin(self):
        superutilisateur = self.m["directeur"].utilisateur
        superutilisateur.is_superuser = True
        superutilisateur.save(update_fields=["is_superuser"])
        client = self.connecter(self.m["directeur"])
        page = client.get(reverse("etablissements"))
        self.assertContains(page, "Créer un nouvel établissement")
        reponse = client.post(reverse("etablissements"), {
            "nom_etablissement": "Mon établissement personnel",
            "type_etablissement": TypeEtablissement.SCOLAIRE,
        })
        self.assertRedirects(reponse, reverse("demarrage"), fetch_redirect_response=False)
        appartenance = Appartenance.sans_filtre.get(
            utilisateur=superutilisateur, etablissement__nom="Mon établissement personnel",
        )
        self.assertEqual(appartenance.role.nom, "Administrateur de l'établissement")
        self.assertIn("pedagogie.gerer", appartenance.role.codes)
        self.assertEqual(client.session["etablissement_id"], appartenance.etablissement_id)
        self.assertEqual(client.get(reverse("academique:annees")).status_code, 200)
        self.assertEqual(client.get(reverse("pedagogie:matieres")).status_code, 200)

    def test_les_filtres_se_soumettent_automatiquement(self):
        secretaire = self.connecter(self.m["secretaire"])
        inscriptions = secretaire.get(reverse("apprenants:inscriptions"))
        self.assertContains(inscriptions, 'data-auto-filtre')
        self.assertNotContains(inscriptions, ">Filtrer</button>", html=False)

        apprenants_page = secretaire.get(reverse("apprenants:liste"))
        self.assertContains(apprenants_page, 'data-auto-filtre')
        self.assertNotContains(apprenants_page, ">Rechercher</button>", html=False)

        directeur = self.connecter(self.m["directeur"])
        resultats = directeur.get(reverse("evaluations:resultats"))
        self.assertContains(resultats, 'data-auto-filtre')
        self.assertNotContains(resultats, ">Filtrer</button>", html=False)

        responsable = creer_membre(
            self.m["etab"], "rp_filtre", "rp_filtre@ecole.test", "MotDePasse!2026", "Responsable pédagogique"
        )
        niveau = self.connecter(responsable).get(reverse("pedagogie:niveau", args=[self.m["n7"].pk]))
        self.assertContains(niveau, 'data-auto-filtre')
        self.assertNotContains(niveau, "onchange=")

        admissions = self.connecter(self.m["directeur"]).get(reverse("admissions:liste"))
        self.assertContains(admissions, 'data-auto-filtre')
        self.assertNotContains(admissions, ">Filtrer</button>", html=False)

        emploi = self.connecter(self.m["directeur"]).get(reverse("emploi_du_temps:gestion"))
        self.assertContains(emploi, 'data-auto-filtre')
        self.assertNotContains(emploi, "onchange=")

    def test_anonyme_redirige_vers_la_connexion(self):
        reponse = self.client.get(reverse("tableau_de_bord"))
        self.assertRedirects(reponse, "/connexion/?next=/tableau-de-bord/")
        self.assertEqual(self.client.get(reverse("connexion")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accueil_public")).status_code, 200)

    def test_connexion_par_formulaire(self):
        reponse = self.client.post(reverse("connexion"), {"username": self.m["prof"].utilisateur.email, "password": "MotDePasse!2026"})
        self.assertRedirects(reponse, reverse("tableau_de_bord"), fetch_redirect_response=False)

    def test_barre_mobile_exactement_cinq_acces_par_role(self):
        for cle, libelles in (
            ("prof", ["Accueil", "Classes", "Notes", "Bulletins"]),
            ("directeur", ["Accueil", "Personnel", "Académique", "Rapports"]),
        ):
            reponse = self.connecter(self.m[cle]).get(reverse("tableau_de_bord"))
            self.assertEqual([e["libelle"] for e in reponse.context["navigation"]["principales"]], libelles)
            self.assertContains(reponse, 'class="navigation-mobile')
            self.assertContains(reponse, 'id="panneauPlus"')
            self.assertContains(reponse, "bi-list")  # icône des trois barres

    def test_terminologie_et_fonctionnalites_par_profil(self):
        classique = profil_etablissement(TypeEtablissement.SCOLAIRE)
        universite = profil_etablissement(TypeEtablissement.UNIVERSITAIRE)
        professionnel = profil_etablissement(TypeEtablissement.PROFESSIONNEL)

        self.assertEqual(
            (classique["libelles"]["apprenants"], classique["libelles"]["groupes"],
             classique["libelles"]["cours"], classique["libelles"]["evaluations"]),
            ("Élèves", "Classes", "Matières", "Bulletins"),
        )
        self.assertEqual(
            (universite["libelles"]["apprenants"], universite["libelles"]["groupes"],
             universite["libelles"]["cours"], universite["libelles"]["evaluations"]),
            ("Étudiants", "Programmes / Filières", "Unités d'Enseignement (UE)",
             "Relevés de notes / Crédits"),
        )
        self.assertEqual(
            (professionnel["libelles"]["apprenants"], professionnel["libelles"]["groupes"],
             professionnel["libelles"]["cours"], professionnel["libelles"]["evaluations"]),
            ("Stagiaires / Apprenants", "Sessions / Ateliers", "Modules pratiques",
             "Attestations de compétences"),
        )
        self.assertTrue(classique["fonctionnalites"]["parents_tuteurs"])
        self.assertTrue(classique["fonctionnalites"]["appels_quotidiens"])
        self.assertTrue(universite["fonctionnalites"]["credits_ects"])
        self.assertTrue(universite["fonctionnalites"]["prerequis_modules"])
        self.assertTrue(professionnel["fonctionnalites"]["planning_flexible"])
        self.assertTrue(professionnel["fonctionnalites"]["attestations_competences"])
        reponse = self.connecter(self.m["secretaire"]).get(reverse("tableau_de_bord"))
        self.assertEqual(len(reponse.context["navigation"]["principales"]), 4)

    def test_navigation_limitee_aux_permissions(self):
        reponse = self.connecter(self.m["prof"]).get(reverse("tableau_de_bord"))
        routes = {e["route"] for groupe in reponse.context["navigation"]["sidebar"].values() for e in groupe}
        self.assertNotIn("personnel", routes)
        self.assertNotIn("apprenants:inscriptions", routes)
        self.assertIn("evaluations:mes_evaluations", routes)
        entrees_cahier = {
            entree["libelle"]: entree["url"]
            for entree in reponse.context["navigation"]["sidebar"]["Vie scolaire"]
            if entree["cle"] in {"cahier_gerer", "devoirs_gerer"}
        }
        self.assertEqual(entrees_cahier["Séances du cahier"], reverse("cahier:entrees"))
        self.assertEqual(entrees_cahier["Devoirs"], reverse("cahier:devoirs"))
        panneau = reponse.content.decode()
        self.assertIn('href="/cahier/devoirs/"', panneau)

    def test_permissions_verifiees_cote_serveur(self):
        client = self.connecter(self.m["prof"])
        for nom in ("personnel", "academique:annees", "apprenants:liste", "apprenants:inscription_creer", "pedagogie:matieres"):
            self.assertEqual(client.get(reverse(nom)).status_code, 403, nom)
        client = self.connecter(self.m["secretaire"])
        self.assertEqual(client.get(reverse("apprenants:inscription_creer")).status_code, 200)
        self.assertEqual(client.get(reverse("evaluations:mes_evaluations")).status_code, 403)

    def test_pages_principales_du_directeur(self):
        client = self.connecter(self.m["directeur"])
        for nom in ("tableau_de_bord", "profil", "etablissements", "personnel", "parametres", "abonnement", "demarrage", "rapports",
                    "academique:annees", "academique:annee_creer", "academique:structure", "apprenants:liste",
                    "apprenants:inscriptions", "evaluations:resultats", "evaluations:classes"):
            self.assertEqual(client.get(reverse(nom)).status_code, 200, nom)
        self.assertEqual(client.get(reverse("academique:periodes", args=[self.m["annee"].pk])).status_code, 200)

    def test_pages_du_responsable_pedagogique(self):
        creer_membre(self.m["etab"], "rp", "rp@x.test", "MotDePasse!2026", "Responsable pédagogique")
        from applications.noyau.models import Appartenance

        rp = Appartenance.sans_filtre.get(utilisateur__username="rp")
        client = self.connecter(rp)
        for nom in ("pedagogie:matieres", "pedagogie:affectations"):
            self.assertEqual(client.get(reverse(nom)).status_code, 200, nom)
        self.assertEqual(client.get(reverse("pedagogie:niveau", args=[self.m["n7"].pk])).status_code, 200)


class TestsIsolation(BaseInterface):
    def test_aucune_fuite_entre_etablissements(self):
        intrus = inscrire(self.autre, "Secret")
        client = self.connecter(self.m["directeur"])
        self.assertEqual(client.get(reverse("apprenants:detail", args=[intrus.apprenant_id])).status_code, 404)
        self.assertEqual(client.get(reverse("apprenants:inscription_detail", args=[intrus.pk])).status_code, 404)
        self.assertEqual(client.get(reverse("academique:periodes", args=[self.autre["annee"].pk])).status_code, 404)
        rp = creer_membre(self.m["etab"], "rp_iso", "rp_iso@x.test", "MotDePasse!2026", "Responsable pédagogique")
        self.assertEqual(self.connecter(rp).get(reverse("pedagogie:niveau", args=[self.autre["n7"].pk])).status_code, 404)
        client = self.connecter(self.m["directeur"])
        reponse = client.get(reverse("apprenants:liste") + "?q=Secret")
        self.assertNotContains(reponse, "SECRET")
        post = client.post(reverse("apprenants:inscription_action", args=[intrus.pk]), {"action": "decider", "decision": "REJETER", "motif": "x"})
        self.assertEqual(post.status_code, 404)

    def test_choix_d_un_autre_etablissement_interdit(self):
        client = self.connecter(self.m["directeur"])
        reponse = client.post(reverse("choisir_etablissement", args=[self.autre["etab"].pk]))
        self.assertEqual(reponse.status_code, 403)

    def test_formulaires_ne_proposent_que_les_donnees_de_l_etablissement(self):
        inscrire(self.autre, "Etranger")
        client = self.connecter(self.m["secretaire"])
        reponse = client.get(reverse("apprenants:inscription_creer"))
        self.assertNotContains(reponse, "ETRANGER")
        self.assertNotContains(reponse, self.autre["classe_a"].nom + "</option>") if self.autre["classe_a"].nom != self.m["classe_a"].nom else None

    def test_utilisateur_sans_etablissement_ne_voit_rien(self):
        from applications.noyau.models import Utilisateur

        orphelin = Utilisateur.objects.create_user("orphelin", "o@x.test", "MotDePasse!2026")
        self.client.force_login(orphelin)
        self.assertRedirects(self.client.get(reverse("tableau_de_bord")), reverse("etablissements"))
        self.assertEqual(self.client.get(reverse("apprenants:liste")).status_code, 403)

    def test_enseignant_ne_configure_pas_la_matiere_d_un_collegue(self):
        collegue = creer_membre(self.m["etab"], "prof2", "prof2@x.test", "MotDePasse!2026", "Enseignant")
        client = self.connecter(collegue)
        url = reverse("evaluations:configuration", args=[self.m["affectation"].pk, self.m["periode1"].pk])
        self.assertEqual(client.get(url).status_code, 403)


class TestsParcours(BaseInterface):
    def test_parcours_inscription_secretaire_puis_directeur(self):
        sec = self.connecter(self.m["secretaire"])
        reponse = sec.post(reverse("apprenants:creer"), {
            "nom": "durand", "prenoms": "Marie", "sexe": "F", "date_naissance": "2013-04-02",
            "responsable_nom": "Durand", "responsable_prenoms": "Paul", "responsable_telephone": "555", "responsable_lien": "PERE",
        })
        apprenant = Apprenant.objects.get(nom="DURAND")
        self.assertRedirects(reponse, f"/apprenants/inscriptions/nouvelle/?apprenant={apprenant.pk}", fetch_redirect_response=False)
        self.assertEqual(apprenant.liens_responsables.count(), 1)
        reponse = sec.post(reverse("apprenants:inscription_creer"), {
            "apprenant": apprenant.pk, "niveau": self.m["n7"].pk, "classe": self.m["classe_a"].pk, "type_inscription": "NOUVELLE",
        })
        inscription = Inscription.objects.get(apprenant=apprenant)
        self.assertEqual(inscription.statut, "EN_ATTENTE")
        # la secrétaire ne peut pas valider
        sec.post(reverse("apprenants:inscription_action", args=[inscription.pk]), {"action": "decider", "decision": "VALIDER"})
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, "EN_ATTENTE")
        # le directeur valide
        directeur = self.connecter(self.m["directeur"])
        directeur.post(reverse("apprenants:inscription_action", args=[inscription.pk]), {"action": "decider", "decision": "VALIDER"})
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, "VALIDEE")
        # un doublon est refusé avec un message clair
        sec = self.connecter(self.m["secretaire"])
        reponse = sec.post(reverse("apprenants:inscription_creer"), {
            "apprenant": apprenant.pk, "niveau": self.m["n7"].pk, "type_inscription": "NOUVELLE"})
        self.assertContains(reponse, "a déjà une inscription")

    def test_rejet_exige_un_motif(self):
        inscription = inscrire(self.m, "Rejet", valider=False)
        directeur = self.connecter(self.m["directeur"])
        reponse = directeur.post(reverse("apprenants:inscription_action", args=[inscription.pk]),
                                 {"action": "decider", "decision": "REJETER", "motif": ""}, follow=True)
        self.assertContains(reponse, "motif est obligatoire")
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, "EN_ATTENTE")

    def test_enseignant_configure_saisit_et_direction_publie(self):
        academique.ouvrir_periode(self.m["periode1"])
        ins = inscrire(self.m, "Eleve")
        prof = self.connecter(self.m["prof"])
        url = reverse("evaluations:configuration", args=[self.m["affectation"].pk, self.m["periode1"].pk])
        # somme incorrecte : refus avec explication
        reponse = prof.post(url, {"action": "valider", "intitule": ["Devoir", "Examen"], "bareme": ["20", "60"]}, follow=True)
        self.assertContains(reponse, "il manque 20")
        # somme correcte : validation puis saisie
        reponse = prof.post(url, {"action": "valider", "intitule": ["Devoir", "Examen"], "bareme": ["30", "70"]})
        config = evaluations.ConfigurationEvaluation.objects.get()
        self.assertRedirects(reponse, reverse("evaluations:saisie", args=[config.pk]), fetch_redirect_response=False)
        c1, c2 = config.composantes.all()
        prof.post(reverse("evaluations:saisie", args=[config.pk]), {
            f"note_{ins.pk}_{c1.pk}": "25", f"etat_{ins.pk}_{c1.pk}": "SAISIE",
            f"note_{ins.pk}_{c2.pk}": "50", f"etat_{ins.pk}_{c2.pk}": "SAISIE",
        })
        resultat = evaluations.ResultatPeriode.objects.get(inscription=ins)
        self.assertEqual(resultat.statut, "REUSSI")
        # note invalide : message d'erreur, rien n'est modifié
        reponse = prof.post(reverse("evaluations:saisie", args=[config.pk]), {
            f"note_{ins.pk}_{c1.pk}": "99", f"etat_{ins.pk}_{c1.pk}": "SAISIE"}, follow=True)
        self.assertContains(reponse, "doit être comprise entre 0 et 30")
        # publication par la direction, puis export
        directeur = self.connecter(self.m["directeur"])
        directeur.post(reverse("evaluations:synthese", args=[config.pk]), {"action": "publier"})
        resultat.refresh_from_db()
        self.assertTrue(resultat.publie)
        excel = directeur.get(reverse("evaluations:resultats") + "?export=excel")
        self.assertEqual(excel["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        pdf = directeur.get(reverse("evaluations:resultats") + "?export=pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        # l'enseignant ne peut pas dépublier ni consulter ce qui n'est pas à lui sans motif
        self.assertContains(prof.get(reverse("evaluations:resultats")), "Eleve".upper())

    def test_portail_apprenant_et_parent(self):
        academique.ouvrir_periode(self.m["periode1"])
        ins = inscrire(self.m, "Portail")
        config = evaluations.creer_configuration(self.m["affectation"], self.m["periode1"])
        evaluations.definir_composantes(config, [("Examen", 100)])
        evaluations.valider_configuration(config)
        composante = config.composantes.get()
        evaluations.saisir_notes(config, [{"inscription_id": ins.pk, "composante_id": composante.pk, "valeur": "80", "etat": "SAISIE"}], self.m["prof"])
        eleve = creer_membre(self.m["etab"], "eleve", "eleve@x.test", "MotDePasse!2026", "Apprenant")
        ins.apprenant.utilisateur = eleve.utilisateur
        ins.apprenant.save()
        client = self.connecter(eleve)
        tableau = client.get(reverse("tableau_de_bord"))
        self.assertTrue(tableau.context["profil_apprenant"])
        self.assertContains(tableau, "Mon parcours")
        self.assertNotContains(client.get(reverse("evaluations:portail")), "80/100")
        evaluations.publier_resultats(config, self.m["directeur"].utilisateur)
        self.assertContains(client.get(reverse("evaluations:portail")), "80/100")
        self.assertEqual(client.get(reverse("evaluations:resultats")).status_code, 403)
        self.assertEqual(client.get(reverse("apprenants:liste")).status_code, 403)
        # parent
        parent = creer_membre(self.m["etab"], "parent", "parent@x.test", "MotDePasse!2026", "Parent")
        responsable = apprenants.creer_responsable(self.m["etab"], "Parent")
        responsable.utilisateur = parent.utilisateur
        responsable.save()
        from applications.apprenants.models import LienResponsable

        LienResponsable.sans_filtre.create(etablissement=self.m["etab"], apprenant=ins.apprenant, responsable=responsable)
        self.assertContains(self.connecter(parent).get(reverse("evaluations:portail")), "80/100")

    def test_universite_interface(self):
        u = monde_universitaire()
        directeur = creer_membre(u["etab"], "dir_u", "dir@u.test", "MotDePasse!2026", "Directeur")
        client = self.connecter(directeur)
        reponse = client.get(reverse("academique:structure"))
        self.assertContains(reponse, "Faculté des Sciences")
        self.assertContains(reponse, "Années d&#x27;études")
        self.assertNotContains(reponse, "Ajouter la classe")
        reponse = client.get(reverse("academique:periodes", args=[u["annee"].pk]))
        self.assertContains(reponse, "Semestre 1")
        sec = creer_membre(u["etab"], "sec_u", "sec@u.test", "MotDePasse!2026", "Secrétaire")
        app = apprenants.creer_apprenant(u["etab"], "Etud", "Paul", "M", date(2004, 1, 1))
        reponse = self.connecter(sec).post(reverse("apprenants:inscription_creer"), {
            "apprenant": app.pk, "niveau": u["niveau"].pk, "programme": u["programme"].pk, "type_inscription": "NOUVELLE"})
        self.assertEqual(Inscription.objects.get().programme, u["programme"])

    def test_gestion_des_periodes_par_l_interface(self):
        client = self.connecter(self.m["directeur"])
        client.post(reverse("academique:periode_action", args=[self.m["periode1"].pk]), {"action": "ouvrir"})
        self.m["periode1"].refresh_from_db()
        self.assertEqual(self.m["periode1"].statut, "OUVERTE")
        client.post(reverse("academique:periode_action", args=[self.m["periode1"].pk]), {"action": "saisie_off"})
        self.m["periode1"].refresh_from_db()
        self.assertFalse(self.m["periode1"].saisie_ouverte)


class TestsAjoutRapide(BaseInterface):
    def test_creation_ajax_d_un_apprenant_sans_perdre_la_page_parent(self):
        client = self.connecter(self.m["secretaire"])
        page = client.get(reverse("apprenants:inscription_creer"))
        self.assertContains(page, 'data-ajout-rapide-cible="apprenant"')

        url = reverse("ajout_rapide", args=["apprenant"])
        self.assertEqual(client.get(url).status_code, 200)
        reponse = client.post(url, {
            "nom": "Nouveau",
            "prenoms": "Dossier",
            "sexe": "F",
            "date_naissance": "2012-04-15",
        })

        self.assertEqual(reponse.status_code, 201)
        donnees = reponse.json()
        apprenant = Apprenant.objects.get(pk=donnees["id"])
        self.assertEqual(apprenant.etablissement_id, self.m["etab"].pk)
        self.assertEqual(donnees["label"], "NOUVEAU Dossier")

    def test_creation_ajax_matiere_et_erreurs_de_validation(self):
        rp = creer_membre(self.m["etab"], "rp_ajax", "rp_ajax@x.test", "MotDePasse!2026", "Responsable pédagogique")
        client = self.connecter(rp)
        url = reverse("ajout_rapide", args=["matiere"])

        invalide = client.post(url, {"nom": ""})
        self.assertEqual(invalide.status_code, 400)
        self.assertIn("nom", invalide.json()["errors"])

        reponse = client.post(url, {"nom": "Sciences"})
        self.assertEqual(reponse.status_code, 201)
        self.assertTrue(Matiere.objects.filter(etablissement=self.m["etab"], nom="Sciences").exists())

    def test_creation_ajax_d_un_responsable_met_a_jour_le_contexte_parent(self):
        client = self.connecter(self.m["directeur"])
        page = client.get(reverse("personnel"))
        self.assertContains(page, 'data-ajout-rapide-cible="responsable"')

        reponse = client.post(reverse("ajout_rapide", args=["responsable"]), {
            "nom": "Parent",
            "prenoms": "Nouveau",
            "email": "parent.nouveau@ecole.test",
        })
        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(reponse.json()["champs_parent"]["email"], "parent.nouveau@ecole.test")

    def test_creation_ajax_refusee_sans_permission_de_gerer_les_apprenants(self):
        comptable = creer_membre(
            self.m["etab"], "comptable_ajax", "comptable_ajax@x.test", "MotDePasse!2026", "Comptable"
        )
        client = self.connecter(comptable)
        url = reverse("ajout_rapide", args=["apprenant"])
        self.assertEqual(client.get(url).status_code, 403)
        page = client.get(reverse("finances:paiement_creer"))
        self.assertNotContains(page, 'data-ajout-rapide-cible="apprenant"')

    def test_creation_ajax_d_une_matiere_de_niveau_reprend_le_contexte_classe(self):
        rp = creer_membre(self.m["etab"], "rp_niveau_ajax", "rp_niveau_ajax@x.test", "MotDePasse!2026", "Responsable pédagogique")
        client = self.connecter(rp)
        page = client.get(reverse("pedagogie:niveau", args=[self.m["n7"].pk]))
        self.assertContains(page, 'data-ajout-rapide-cible="matiere_niveau"')

        url = reverse("ajout_rapide", args=["matiere_niveau"])
        schema = client.get(url, {"classe": self.m["classe_a"].pk}).json()
        champ_niveau = next(champ for champ in schema["fields"] if champ["name"] == "niveau")
        self.assertEqual(champ_niveau["value"], str(self.m["n7"].pk))

        matiere = pedagogie.creer_matiere(self.m["etab"], "Sciences naturelles")
        reponse = client.post(url + f"?classe={self.m['classe_a'].pk}", {
            "niveau": self.m["n7"].pk,
            "matiere": matiere.pk,
            "bareme": "50",
            "coefficient": "1",
        })
        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(reponse.json()["relations"]["niveau"], self.m["n7"].pk)


class TestsGraphiquesTableauDeBord(BaseInterface):
    def test_graphes_aggregent_l_annee_active_et_isolent_les_statuts(self):
        eleve_paye = inscrire(self.m, "Payé", self.m["classe_a"])
        eleve_retard = inscrire(self.m, "En retard", self.m["classe_a"])
        eleve_partiel = inscrire(self.m, "Partiel", self.m["classe_a"])
        eleve_a_venir = inscrire(self.m, "À venir", self.m["classe_b"])
        inscrire(self.autre, "Autre établissement")
        aujourd_hui = timezone.localdate()

        factures = []
        for ordre, inscription in enumerate(
            (eleve_paye, eleve_retard, eleve_partiel, eleve_a_venir), start=1,
        ):
            facture = Facture.sans_filtre.create(
                etablissement=self.m["etab"], inscription=inscription,
                numero=f"TEST-{ordre}", total=Decimal("100"),
            )
            Echeance.sans_filtre.create(
                etablissement=self.m["etab"], facture=facture, ordre=1, libelle="Scolarité",
                montant=Decimal("100"),
                date_limite=aujourd_hui - timedelta(days=1) if ordre < 3 else aujourd_hui + timedelta(days=30),
            )
            factures.append(facture)
        Paiement.sans_filtre.create(
            etablissement=self.m["etab"], apprenant=eleve_paye.apprenant, facture=factures[0],
            montant=Decimal("100"), motif="Paiement réglé",
        )
        Paiement.sans_filtre.create(
            etablissement=self.m["etab"], apprenant=eleve_partiel.apprenant, facture=factures[2],
            montant=Decimal("25"), motif="Paiement partiel",
        )
        for inscription, valeur in ((eleve_paye, "80"), (eleve_retard, "60")):
            ResultatPeriode.sans_filtre.create(
                etablissement=self.m["etab"], inscription=inscription,
                matiere_niveau=self.m["mn"], periode=self.m["periode1"],
                total=Decimal(valeur), bareme_applique=Decimal("100"),
                pourcentage=Decimal(valeur), statut=ResultatPeriode.Statut.REUSSI, publie=True,
            )

        reponse = self.connecter(self.m["directeur"]).get(reverse("tableau_de_bord"))
        graphiques = reponse.context["graphiques_tableau"]

        self.assertEqual(graphiques["effectifs"], {
            "labels": ["7e année · 7e A", "7e année · 7e B"],
            "values": [3, 1],
            "series_label": "Apprenants",
        })
        self.assertEqual(graphiques["paiements"], {
            "labels": ["Payé", "En retard", "Partiel", "À venir"],
            "values": [1, 1, 1, 1],
        })
        self.assertEqual(graphiques["moyennes"]["values"], [14.0, None, None])
        self.assertContains(reponse, 'id="donnees-graphiques-tableau"')
        self.assertContains(reponse, "vendor/chart.umd.min.js")

    def test_graphes_visibles_seulement_avec_les_permissions_correspondantes(self):
        reponse = self.connecter(self.m["secretaire"]).get(reverse("tableau_de_bord"))

        self.assertEqual(set(reponse.context["graphiques_tableau"]), {"effectifs"})
        self.assertContains(reponse, "Répartition des apprenants")
        self.assertNotContains(reponse, "Statut des paiements")
        self.assertNotContains(reponse, "Évolution de la moyenne générale")

    def test_administrateur_tenant_ne_voit_pas_le_portail_apprenant_sans_dossier_lie(self):
        administrateur = creer_membre(
            self.m["etab"], "admin_tenant_sans_dossier", "admin.tenant@ecole.test",
            "MotDePasse!2026", "Administrateur de l'établissement",
        )
        reponse = self.connecter(administrateur).get(reverse("tableau_de_bord"))

        self.assertFalse(reponse.context["profil_apprenant"])
        self.assertNotContains(reponse, "Mon parcours")
        self.assertNotContains(reponse, "Aucune inscription active n’est associée")


class TestsMarqueEntete(BaseInterface):
    def test_titre_et_favicon_suivent_la_priorite_tenant_plateforme_secours(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            page_publique = self.client.get(reverse("accueil_public"))
            self.assertContains(page_publique, "<title>", html=False)
            self.assertContains(
                page_publique, "Pilotez votre établissement scolaire avec précision · EduGest", html=False,
            )
            self.assertContains(page_publique, 'href="/static/images/logo.png"', html=False)
            self.assertIsNone(page_publique.context["request"].etablissement)
            self.assertIsNone(page_publique.context["favicon_url"])

            marque = ConfigurationPlateforme.objects.create(
                nom="Marque plateforme",
                logo=SimpleUploadedFile("plateforme.png", b"logo plateforme"),
            )
            page_publique = self.client.get(reverse("accueil_public"))
            self.assertContains(
                page_publique,
                "Pilotez votre établissement scolaire avec précision · Marque plateforme",
                html=False,
            )
            self.assertContains(page_publique, f'href="{marque.logo.url}"', html=False)
            self.assertIsNone(page_publique.context["request"].etablissement)

            self.m["etab"].logo = SimpleUploadedFile("ecole.png", b"logo ecole")
            self.m["etab"].save(update_fields=["logo"])
            page_tenant = self.connecter(self.m["directeur"]).get(reverse("tableau_de_bord"))
            self.assertContains(page_tenant, "Accueil · École A", html=False)
            self.assertContains(page_tenant, f'href="{self.m["etab"].logo.url}"', html=False)
            self.assertEqual(page_tenant.context["request"].etablissement, self.m["etab"])

            self.m["etab"].logo.storage.delete(self.m["etab"].logo.name)
            page_tenant = self.client.get(reverse("tableau_de_bord"))
            self.assertContains(page_tenant, f'href="{marque.logo.url}"', html=False)

            marque.logo.storage.delete(marque.logo.name)
            self.client.logout()
            page_publique = self.client.get(reverse("accueil_public"))
            self.assertContains(page_publique, 'href="/static/images/logo.png"', html=False)
