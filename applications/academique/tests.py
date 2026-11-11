from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from applications.academique import services
from applications.academique.forms import FormulaireAnnee
from applications.academique.models import (
    AnneeAcademique, Classe, Niveau, Periode, PresetAcademique, Programme, SiteEtablissement,
)
from applications.apprenants import services as services_apprenants
from applications.apprenants.models import Inscription
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import TypeEtablissement
from applications.noyau.outils_tests import monde_scolaire, monde_universitaire
from applications.noyau.services import creer_etablissement


class TestsAcademique(TestCase):
    def test_corriger_nom_niveau_sans_modifier_ses_relations(self):
        monde = monde_scolaire()
        services.modifier_niveau(monde["n7"], "7e année corrigée", par=monde["directeur"].utilisateur)
        monde["n7"].refresh_from_db()
        self.assertEqual(monde["n7"].nom, "7e année corrigée")
        self.assertEqual(monde["n7"].classes.count(), 2)

    def test_corriger_nom_classe_sans_modifier_ses_inscriptions(self):
        monde = monde_scolaire()
        inscription = services_apprenants.creer_inscription(
            monde["etab"],
            services_apprenants.creer_apprenant(
                monde["etab"], "Élève", "Test", "M", date(2013, 1, 1)
            ),
            monde["n7"], monde["classe_a"],
        )
        services.modifier_classe(
            monde["classe_a"], "7e A corrigée", par=monde["directeur"].utilisateur
        )
        inscription.refresh_from_db()
        self.assertEqual(inscription.classe_id, monde["classe_a"].pk)
        self.assertEqual(inscription.classe.nom, "7e A corrigée")

    def test_modifier_nom_classe_et_niveau_depuis_lecran_structure(self):
        monde = monde_scolaire()
        self.client.force_login(monde["directeur"].utilisateur)
        reponse = self.client.post(
            reverse("academique:classe_modifier", args=[monde["classe_a"].pk]), {"nom": "7e A corrigée"}
        )
        self.assertRedirects(reponse, reverse("academique:structure"), fetch_redirect_response=False)
        reponse = self.client.post(
            reverse("academique:niveau_modifier", args=[monde["n7"].pk]), {"nom": "7e corrigée"}
        )
        self.assertRedirects(reponse, reverse("academique:structure"), fetch_redirect_response=False)
        monde["classe_a"].refresh_from_db()
        monde["n7"].refresh_from_db()
        self.assertEqual(monde["classe_a"].nom, "7e A corrigée")
        self.assertEqual(monde["n7"].nom, "7e corrigée")

    def test_niveau_inutilise_peut_etre_supprime_depuis_sa_page_de_modification(self):
        monde = monde_scolaire()
        niveau = services.creer_niveau(monde["etab"], "Niveau inutilisé")
        self.client.force_login(monde["directeur"].utilisateur)

        page = self.client.get(reverse("academique:niveau_modifier", args=[niveau.pk]))
        self.assertContains(page, "Supprimer le niveau")

        reponse = self.client.post(reverse("academique:niveau_supprimer", args=[niveau.pk]))

        self.assertRedirects(reponse, reverse("academique:structure"), fetch_redirect_response=False)
        self.assertFalse(Niveau.sans_filtre.filter(pk=niveau.pk).exists())

    def test_niveau_utilise_ne_peut_pas_etre_supprime(self):
        monde = monde_scolaire()
        self.client.force_login(monde["directeur"].utilisateur)

        reponse = self.client.post(reverse("academique:niveau_supprimer", args=[monde["n7"].pk]), follow=True)

        self.assertContains(reponse, "ne peut pas être supprimé")
        self.assertContains(reponse, "classe(s)")
        self.assertTrue(Niveau.sans_filtre.filter(pk=monde["n7"].pk).exists())

    def test_preset_cree_uniquement_les_niveaux_manquants(self):
        monde = monde_scolaire()
        preset = PresetAcademique.sans_filtre.create(
            etablissement=monde["etab"], nom="Cycle fondamental",
            niveaux=["7e année", "8e année", "9e année"],
        )

        ajoutes = services.appliquer_preset(preset)

        self.assertEqual([niveau.nom for niveau in ajoutes], ["9e année"])
        self.assertEqual(Niveau.objects.filter(etablissement=monde["etab"], nom="7e année").count(), 1)

    def test_classe_rattachee_a_un_site_et_site_autre_tenant_refuse(self):
        monde = monde_scolaire()
        site = SiteEtablissement.sans_filtre.create(
            etablissement=monde["etab"], nom="Campus Nord", code="NORD"
        )
        classe = services.creer_classe(monde["n7"], monde["annee"], "7e C", site=site)
        self.assertEqual(classe.site, site)

        autre = monde_scolaire("Autre établissement")
        autre_site = SiteEtablissement.sans_filtre.create(
            etablissement=autre["etab"], nom="Campus", code="CAMPUS"
        )
        with self.assertRaises(ErreurMetier):
            services.creer_classe(monde["n7"], monde["annee"], "7e D", site=autre_site)

    def test_fk_academiques_et_inscription_refusent_les_tenants_melanges(self):
        universitaire = monde_universitaire()
        autre_universite = monde_universitaire("Autre université")
        with self.assertRaises(ValidationError):
            Programme(
                etablissement=universitaire["etab"], faculte=autre_universite["faculte"], nom="Invalide"
            ).full_clean()
        with self.assertRaises(ValidationError):
            Niveau(
                etablissement=universitaire["etab"], programme=autre_universite["programme"],
                nom="Invalide", ordre=2,
            ).full_clean()
        with self.assertRaises(ValidationError):
            Niveau.sans_filtre.create(
                etablissement=universitaire["etab"], programme=autre_universite["programme"],
                nom="Invalide", ordre=2,
            )

        monde = monde_scolaire()
        autre_ecole = monde_scolaire("Autre école")
        with self.assertRaises(ValidationError):
            Classe(
                etablissement=monde["etab"], niveau=monde["n7"], annee=autre_ecole["annee"], nom="Invalide"
            ).full_clean()
        apprenant = services_apprenants.creer_apprenant(
            monde["etab"], "Test", "Élève", "M", date(2013, 1, 1)
        )
        with self.assertRaises(ValidationError):
            Inscription(
                etablissement=monde["etab"], apprenant=apprenant, annee=autre_ecole["annee"],
                niveau=monde["n7"], classe=monde["classe_a"],
            ).full_clean()

    def test_niveau_doublon_refuse_a_la_sauvegarde_du_modele(self):
        monde = monde_scolaire()
        with self.assertRaises(ValidationError):
            Niveau.sans_filtre.create(
                etablissement=monde["etab"], nom=monde["n7"].nom, ordre=99
            )

    def test_preference_de_periodes_utilisee_pour_les_nouvelles_annees(self):
        monde = monde_scolaire()
        monde["etab"].parametres.nombre_periodes_par_annee = 5
        monde["etab"].parametres.save(update_fields=["nombre_periodes_par_annee"])

        formulaire = FormulaireAnnee(etablissement=monde["etab"])
        self.assertEqual(formulaire.initial["nombre_periodes"], 5)

        annee = services.creer_annee(
            monde["etab"], "2027-2028", date(2027, 9, 1), date(2028, 6, 30)
        )
        self.assertEqual(annee.periodes.count(), 5)

    def test_ajouter_une_periode_depuis_le_detail_de_l_annee(self):
        monde = monde_scolaire()
        annee = monde["annee"]
        derniere = annee.periodes.get(ordre=3)
        precedente = annee.periodes.get(ordre=2)
        debut_nouvelle = precedente.date_fin + timedelta(days=1)
        debut_derniere = debut_nouvelle + timedelta(days=30)
        client = self.client
        client.force_login(monde["directeur"].utilisateur)

        reponse = client.post(reverse("academique:periode_action", args=[derniere.pk]), {
            "action": "modifier", "nom": derniere.nom, "date_debut": debut_derniere.isoformat(),
            "date_fin": derniere.date_fin.isoformat(),
        })
        self.assertRedirects(reponse, reverse("academique:periodes", args=[annee.pk]))

        reponse = client.post(reverse("academique:periode_creer", args=[annee.pk]), {
            "nom": "Trimestre 4", "date_debut": debut_nouvelle.isoformat(),
            "date_fin": (debut_derniere - timedelta(days=1)).isoformat(),
        })
        self.assertRedirects(reponse, reverse("academique:periodes", args=[annee.pk]))
        nouvelle = annee.periodes.get(nom="Trimestre 4")
        self.assertEqual(nouvelle.ordre, 4)

        reponse = client.get(reverse("academique:periodes", args=[annee.pk]))
        self.assertContains(reponse, "Ajouter une période")
        self.assertContains(reponse, "Modifier")

    def test_modifier_dates_periode_meme_si_cloturee_dans_annee_non_cloturee(self):
        monde = monde_scolaire()
        periode = monde["periode1"]
        services.fermer_periode(periode)
        nouvelle_date_debut = periode.date_debut + timedelta(days=1)

        services.modifier_periode(
            periode, periode.nom, nouvelle_date_debut, periode.date_fin,
            par=monde["directeur"].utilisateur,
        )

        periode.refresh_from_db()
        self.assertEqual(periode.date_debut, nouvelle_date_debut)
        client = self.client
        client.force_login(monde["directeur"].utilisateur)
        reponse = client.get(reverse("academique:periodes", args=[monde["annee"].pk]))
        self.assertContains(reponse, "Modifier")
        self.assertContains(reponse, "Clôturée")

    def test_modifier_dates_annee_puis_prolonger_une_periode(self):
        monde = monde_scolaire()
        annee = monde["annee"]
        derniere = annee.periodes.get(ordre=3)
        date_fin_annee = date(2027, 10, 30)
        self.client.force_login(monde["directeur"].utilisateur)

        reponse = self.client.post(
            reverse("academique:annee_action", args=[annee.pk]),
            {
                "action": "modifier_dates",
                "date_debut": annee.date_debut.isoformat(),
                "date_fin": date_fin_annee.isoformat(),
            },
        )
        self.assertRedirects(
            reponse, reverse("academique:periodes", args=[annee.pk]), fetch_redirect_response=False
        )
        annee.refresh_from_db()
        self.assertEqual(annee.date_fin, date_fin_annee)

        services.modifier_periode(
            derniere, derniere.nom, derniere.date_debut, date_fin_annee,
            par=monde["directeur"].utilisateur,
        )

        annee.refresh_from_db()
        derniere.refresh_from_db()
        self.assertEqual(annee.date_fin, date_fin_annee)
        self.assertEqual(derniere.date_fin, date_fin_annee)

    def test_refuser_dates_annee_qui_excluent_une_periode_existante(self):
        monde = monde_scolaire()
        with self.assertRaises(ErreurMetier):
            services.modifier_dates_annee(
                monde["annee"], monde["annee"].date_debut, date(2027, 3, 1)
            )

    def test_periodes_configurables_et_couvrant_l_annee(self):
        etab = creer_etablissement("E", TypeEtablissement.SCOLAIRE)
        for nombre in (3, 4):
            annee = services.creer_annee(etab, f"A{nombre}", date(2026, 9, 1), date(2027, 6, 30), nombre)
            periodes = list(annee.periodes.all())
            self.assertEqual(len(periodes), nombre)
            self.assertEqual(periodes[0].date_debut, annee.date_debut)
            self.assertEqual(periodes[-1].date_fin, annee.date_fin)
            services.valider_periodes(annee)
        self.assertTrue(periodes[0].nom.startswith("Trimestre"))

    def test_universite_utilise_des_semestres(self):
        m = monde_universitaire()
        self.assertEqual(m["annee"].periodes.count(), 2)
        self.assertTrue(m["annee"].periodes.first().nom.startswith("Semestre"))

    def test_une_seule_annee_active(self):
        m = monde_scolaire()
        suivante = services.creer_annee(m["etab"], "2027-2028", date(2027, 9, 1), date(2028, 6, 30))
        with self.assertRaises(ErreurMetier):
            services.activer_annee(suivante)
        services.cloturer_annee(m["annee"])
        services.activer_annee(suivante)
        self.assertEqual(AnneeAcademique.objects.filter(statut="ACTIVE").count(), 1)

    def test_annee_dates_invalides_et_doublon(self):
        m = monde_scolaire()
        with self.assertRaises(ErreurMetier):
            services.creer_annee(m["etab"], "X", date(2027, 1, 1), date(2026, 1, 1))
        with self.assertRaises(ErreurMetier):
            services.creer_annee(m["etab"], "2026-2027", date(2026, 9, 1), date(2027, 6, 30))

    def test_chevauchement_de_periodes_refuse(self):
        m = monde_scolaire(activer=False)
        p2 = m["annee"].periodes.get(ordre=2)
        p2.date_debut = m["annee"].periodes.get(ordre=1).date_fin
        p2.save()
        with self.assertRaises(ErreurMetier):
            services.activer_annee(m["annee"])

    def test_ouverture_et_fermeture_des_periodes(self):
        m = monde_scolaire()
        services.ouvrir_periode(m["periode1"])
        m["periode1"].refresh_from_db()
        self.assertTrue(m["periode1"].saisie_ouverte)
        services.basculer_saisie(m["periode1"], False)
        services.fermer_periode(m["periode1"])
        with self.assertRaises(ErreurMetier):
            services.ouvrir_periode(m["periode1"])

    def test_niveau_et_classe_selon_le_type(self):
        u = monde_universitaire()
        with self.assertRaises(ErreurMetier):
            services.creer_niveau(u["etab"], "Sans programme")
        with self.assertRaises(ErreurMetier):
            services.creer_classe(u["niveau"], u["annee"], "L1 A")
        s = monde_scolaire("École Z")
        with self.assertRaises(ErreurMetier):
            services.creer_faculte(s["etab"], "Faculté")
        with self.assertRaises(ErreurMetier):
            services.creer_niveau(s["etab"], "7e année")  # doublon
        self.assertEqual(s["n8"].ordre, 2)

    def test_plusieurs_classes_dans_un_meme_niveau(self):
        m = monde_scolaire()
        self.assertEqual(m["n7"].classes.count(), 2)
        with self.assertRaises(ErreurMetier):
            services.creer_classe(m["n7"], m["annee"], "7e A")

    def test_duplication_annee(self):
        m = monde_scolaire()
        services.cloturer_annee(m["annee"])
        nouvelle = services.creer_annee(m["etab"], "2027-2028", date(2027, 9, 1), date(2028, 6, 30))
        classes, matieres = services.dupliquer_annee(m["annee"], nouvelle)
        self.assertEqual((classes, matieres), (2, 1))
        self.assertEqual(Periode.objects.filter(annee=nouvelle).count(), 3)
