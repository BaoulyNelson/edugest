"""Tests SaaS : inscription libre, espaces isolés, invitations, abonnements, plateforme."""
import re
import smtplib
from datetime import datetime, timezone as datetime_timezone
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ValidationError
from django.core import mail
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from applications.academique.models import AnneeAcademique, Classe, Niveau
from applications.apprenants import services as apprenants
from applications.pedagogie.models import Matiere, MatiereNiveau
from applications.noyau import saas
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.forms import FormulaireIdentite
from applications.noyau.middleware import MiddlewareLocalisation
from applications.noyau.models import (
    Abonnement, Appartenance, ConfigurationPlateforme, Etablissement, EvenementPaiement, Invitation,
    JournalAudit, Plan, Role, Utilisateur,
)
from applications.noyau.outils_tests import monde_scolaire
from applications.noyau.services import creer_membre

DONNEES = {
    "nom_etablissement": "Collège Saint-Louis", "type_etablissement": "SCOLAIRE", "prenom": "Marie", "nom": "Joseph",
    "username": "mariejoseph", "email": "marie@exemple.com", "mot_de_passe": "Secret!Fort2026",
}


class TestsInscriptionLibre(TestCase):
    def test_page_d_accueil_publique(self):
        reponse = self.client.get("/")
        self.assertContains(reponse, "Créer mon établissement")
        self.assertContains(reponse, "Essai gratuit")
        self.assertContains(reponse, "inscription/?plan=essai")
        self.assertContains(reponse, "inscription/?plan=standard")
        self.assertContains(reponse, "inscription/?plan=premium")

    def test_plan_demande_est_preselectionne_et_attribue_a_l_abonnement(self):
        page = self.client.get(f"{reverse('inscription')}?plan=standard")
        self.assertEqual(page.context["formulaire"]["plan"].value(), "STANDARD")
        self.assertContains(page, 'value="STANDARD" selected')

        reponse = self.client.post(reverse("inscription"), {**DONNEES, "plan": "PREMIUM"})

        self.assertRedirects(reponse, reverse("demarrage"))
        abonnement = Etablissement.objects.get(nom=DONNEES["nom_etablissement"]).abonnement
        self.assertEqual(abonnement.plan.code, "PREMIUM")
        self.assertEqual(abonnement.statut, Abonnement.Statut.ESSAI)

    def test_plan_invalide_dans_url_utilise_le_plan_essai(self):
        reponse = self.client.get(f"{reverse('inscription')}?plan=plan-inconnu")
        self.assertEqual(reponse.context["formulaire"]["plan"].value(), "ESSAI")

    def test_utilisateur_connecte_peut_revenir_sur_le_site_public(self):
        self.client.post(reverse("inscription"), DONNEES)

        reponse = self.client.get(reverse("accueil_public"))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Accéder à mon tableau de bord")
        self.assertNotContains(reponse, ">Connexion</a>")
        self.assertNotContains(reponse, ">Essai gratuit</a>")
        self.assertRedirects(
            self.client.get(reverse("connexion")),
            reverse("tableau_de_bord"),
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get(reverse("inscription")),
            reverse("etablissements"),
            fetch_redirect_response=False,
        )

    def test_l_utilisateur_cree_lui_meme_son_compte_et_son_etablissement(self):
        reponse = self.client.post(reverse("inscription"), DONNEES)
        self.assertRedirects(reponse, reverse("demarrage"))
        utilisateur = Utilisateur.objects.get(email="marie@exemple.com")
        self.assertEqual(utilisateur.username, "mariejoseph")
        self.assertTrue(utilisateur.check_password("Secret!Fort2026"))
        etablissement = Etablissement.objects.get(nom="Collège Saint-Louis")
        appartenance = Appartenance.sans_filtre.get(utilisateur=utilisateur, etablissement=etablissement)
        self.assertEqual(appartenance.role.nom, "Administrateur de l'établissement")
        self.assertEqual(etablissement.abonnement.statut, "ESSAI")
        self.assertEqual(etablissement.abonnement.plan.code, "ESSAI")
        self.assertEqual(self.client.get(reverse("tableau_de_bord")).status_code, 200)  # déjà connecté
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/verification/", mail.outbox[0].body)

    def test_inscription_d_un_etablissement_professionnel(self):
        reponse = self.client.post(
            reverse("inscription"),
            {**DONNEES, "type_etablissement": "PROFESSIONNEL"},
        )
        self.assertRedirects(reponse, reverse("demarrage"))
        etablissement = Etablissement.objects.get(nom="Collège Saint-Louis")
        self.assertEqual(etablissement.type, "PROFESSIONNEL")
        tableau = self.client.get(reverse("tableau_de_bord"))
        self.assertEqual(tableau.context["libelles"]["apprenants"], "Stagiaires / Apprenants")
        self.assertTrue(tableau.context["fonctionnalites"]["planning_flexible"])
        dossier = self.client.get(reverse("apprenants:creer"))
        self.assertNotContains(dossier, "Responsable légal")
        personnel = self.client.get(reverse("personnel"))
        self.assertNotContains(personnel, "Parent")

    def test_confirmation_de_l_adresse_par_lien(self):
        self.client.post(reverse("inscription"), DONNEES)
        jeton = re.search(r"/verification/([^/\s]+)/", mail.outbox[0].body).group(1)
        self.assertFalse(Utilisateur.objects.get(email="marie@exemple.com").email_verifie)
        self.client.get(reverse("verification_courriel", args=[jeton]))
        self.assertTrue(Utilisateur.objects.get(email="marie@exemple.com").email_verifie)
        self.client.get(reverse("verification_courriel", args=["jeton-falsifie"]), follow=True)

    def test_adresse_deja_utilisee_et_mot_de_passe_faible(self):
        self.client.post(reverse("inscription"), DONNEES)
        self.client.post(reverse("deconnexion"))
        reponse = self.client.post(reverse("inscription"), {**DONNEES, "nom_etablissement": "Autre", "username": "autre"})
        self.assertContains(reponse, "Un compte existe déjà")
        reponse = self.client.post(reverse("inscription"), {
            **DONNEES, "username": "autre", "email": "autre@exemple.com", "mot_de_passe": "12345678",
        })
        self.assertEqual(Utilisateur.objects.filter(email="autre@exemple.com").count(), 0)
        self.assertContains(reponse, "erreur-champ")

    def test_nom_utilisateur_deja_utilise_est_refuse(self):
        Utilisateur.objects.create_user("mariejoseph", "autre@exemple.com", "Secret!Fort2026")
        donnees = {**DONNEES, "email": "nouvelle@exemple.com"}
        reponse = self.client.post(reverse("inscription"), donnees)
        self.assertContains(reponse, "Ce nom d’utilisateur est déjà utilisé.")
        self.assertFalse(Utilisateur.objects.filter(email="nouvelle@exemple.com").exists())

    def test_connexion_par_adresse_email(self):
        page = self.client.get(reverse("connexion"))
        self.assertContains(page, "Nom d’utilisateur ou adresse e-mail")
        self.client.post(reverse("inscription"), DONNEES)
        self.client.post(reverse("deconnexion"))
        mauvais = self.client.post(reverse("connexion"), {"username": "marie@exemple.com", "password": "faux"})
        self.assertContains(mauvais, "Nom d’utilisateur/adresse e-mail ou mot de passe incorrect")
        bon = self.client.post(reverse("connexion"), {"username": "MARIE@exemple.com", "password": "Secret!Fort2026"})
        self.assertRedirects(bon, reverse("tableau_de_bord"), fetch_redirect_response=False)
        self.client.post(reverse("deconnexion"))
        bon = self.client.post(reverse("connexion"), {"username": "mariejoseph", "password": "Secret!Fort2026"})
        self.assertRedirects(bon, reverse("tableau_de_bord"), fetch_redirect_response=False)

    def test_deux_etablissements_homonymes_restent_isoles(self):
        c1, c2 = self.client_class(), self.client_class()
        c1.post(reverse("inscription"), DONNEES)
        c2.post(reverse("inscription"), {
            **DONNEES, "username": "pauljoseph", "email": "paul@exemple.com", "prenom": "Paul",
        })
        e1, e2 = Etablissement.objects.order_by("pk")
        self.assertNotEqual(e1.slug, e2.slug)
        c1.post(reverse("demarrage"), {"designation": "2026-2027", "date_debut": "2026-09-01", "date_fin": "2027-06-30",
                                       "nombre_periodes": 3, "niveaux_standards": "on", "classes_par_niveau": 1})
        self.assertEqual(AnneeAcademique.sans_filtre.filter(etablissement=e1).count(), 1)
        self.assertEqual(AnneeAcademique.sans_filtre.filter(etablissement=e2).count(), 0)
        self.assertEqual(c2.get(reverse("academique:annees")).context["annees"].count(), 0)
        self.assertEqual(c1.get(reverse("academique:annees")).context["annees"].count(), 1)

    def test_un_utilisateur_peut_creer_un_second_etablissement_et_changer_d_espace(self):
        self.client.post(reverse("inscription"), DONNEES)
        self.client.post(reverse("etablissements"), {"nom_etablissement": "Université X", "type_etablissement": "UNIVERSITAIRE"})
        self.assertEqual(Appartenance.sans_filtre.filter(utilisateur__email="marie@exemple.com").count(), 2)
        premier = Etablissement.objects.get(nom="Collège Saint-Louis")
        self.client.post(reverse("choisir_etablissement", args=[premier.pk]))
        self.assertEqual(self.client.get(reverse("tableau_de_bord")).context["request"].etablissement, premier)

    def test_demarrage_rapide_ecole(self):
        self.client.post(reverse("inscription"), DONNEES)
        reponse = self.client.post(reverse("demarrage"), {
            "designation": "2026-2027", "date_debut": "2026-09-01", "date_fin": "2027-06-30", "nombre_periodes": 3,
            "niveaux_standards": "on", "classes_par_niveau": 2}, follow=True)
        self.assertContains(reponse, "est configuré")
        etab = Etablissement.objects.get()
        self.assertEqual(AnneeAcademique.sans_filtre.get(etablissement=etab).statut, "ACTIVE")
        self.assertEqual(Niveau.sans_filtre.filter(etablissement=etab).count(), 7)
        self.assertEqual(Classe.sans_filtre.filter(etablissement=etab).count(), 14)
        self.assertContains(self.client.get(reverse("demarrage")), "déjà active")
        self.assertContains(self.client.get(reverse("tableau_de_bord")), "Les premiers pas")

    def test_demarrage_rapide_universite(self):
        self.client.post(reverse("inscription"), {**DONNEES, "type_etablissement": "UNIVERSITAIRE"})
        self.client.post(reverse("demarrage"), {"designation": "2026-2027", "date_debut": "2026-09-01", "date_fin": "2027-07-31", "nombre_periodes": 2})
        annee = AnneeAcademique.sans_filtre.get()
        self.assertEqual(annee.periodes.count(), 2)
        self.assertEqual(Niveau.sans_filtre.count(), 0)

    def test_demarrage_rapide_professionnel_cree_les_parcours_et_modules_proposes(self):
        self.client.post(reverse("inscription"), {**DONNEES, "type_etablissement": "PROFESSIONNEL"})

        page = self.client.get(reverse("demarrage"))
        self.assertContains(page, "Créer les 5 parcours professionnels et leurs 15 modules")

        self.client.post(reverse("demarrage"), {
            "designation": "2026-2027", "date_debut": "2026-09-01", "date_fin": "2027-06-30",
            "nombre_periodes": 3, "niveaux_standards": "on", "classes_par_niveau": 2,
        })

        self.assertEqual(Niveau.sans_filtre.count(), 5)
        self.assertEqual(Matiere.sans_filtre.count(), 15)
        self.assertEqual(MatiereNiveau.sans_filtre.count(), 15)
        self.assertEqual(Classe.sans_filtre.count(), 0)
        modules_par_parcours = {
            "Informatique & Bureautique": {
                "Microsoft Word & Traitement de texte",
                "Microsoft Excel & Tableurs",
                "Maintenance Informatique & Réseaux",
            },
            "Comptabilité & Gestion": {
                "Comptabilité Générale",
                "Fiscalité & Paie",
                "Logiciel Comptable (QuickBooks / Sage)",
            },
            "Électricité Bâtiment": {
                "Schémas & Installation Électrique",
                "Sécurité Électrique & Normes",
                "Énergie Solaire & Photovoltaïque",
            },
            "Cosmétologie / Esthétique": {
                "Soins du Visage & Dermatologie",
                "Coiffure & Techniques de Coupe",
                "Manucure & Pédicure",
            },
            "Couture & Haute Mode": {
                "Patronage & Coupe",
                "Montage & Assemblage Machine",
                "Stylisme & Finitions",
            },
        }
        for parcours, modules_attendus in modules_par_parcours.items():
            modules_crees = MatiereNiveau.sans_filtre.filter(niveau__nom=parcours)
            self.assertSetEqual(set(modules_crees.values_list("matiere__nom", flat=True)), modules_attendus)
            self.assertSetEqual(set(modules_crees.values_list("bareme", flat=True)), {100})


class TestsInvitations(TestCase):
    def setUp(self):
        self.m = monde_scolaire("École Inv")
        self.admin = Utilisateur.objects.create_user("a", "admin@x.test", "MotDePasse!2026")
        saas.creer_espace(self.admin, "Autre école", "SCOLAIRE")
        self.directeur = self.m["directeur"]
        self.client.force_login(self.directeur.utilisateur)
        self.role_ens = self.m["prof"].role

    def inviter(self, email="nouveau@exemple.com"):
        return self.client.post(reverse("personnel"), {"invitation-email": email, "invitation-role": self.role_ens.pk})

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    @mock.patch("applications.noyau.saas.send_mail", return_value=1)
    def test_le_mode_console_ne_pretend_pas_livrer_l_invitation(self, envoi):
        page = self.client.post(
            reverse("personnel"),
            {"invitation-email": "nouveau@exemple.com", "invitation-role": self.role_ens.pk},
            follow=True,
        )
        self.assertEqual(page.redirect_chain, [(reverse("personnel"), 302)])
        self.assertContains(page, "terminal du serveur")
        envoi.assert_called_once()

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    @mock.patch(
        "applications.noyau.saas.send_mail",
        side_effect=smtplib.SMTPException("SMTP indisponible"),
    )
    def test_un_echec_smtp_est_affiche_et_ne_cree_pas_d_invitation(self, envoi):
        reponse = self.inviter()
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "L&#x27;e-mail n&#x27;a pas pu être envoyé")
        self.assertFalse(Invitation.sans_filtre.filter(email="nouveau@exemple.com").exists())
        envoi.assert_called_once()

    def test_l_invite_cree_lui_meme_son_compte(self):
        self.inviter()
        invitation = Invitation.sans_filtre.get(email="nouveau@exemple.com")
        self.assertEqual(len(mail.outbox), 1)
        lien = re.search(r"/invitation/([^/\s]+)/", mail.outbox[0].body).group(1)
        self.assertEqual(lien, invitation.jeton)
        invite = self.client_class()
        self.assertContains(invite.get(reverse("invitation", args=[lien])), "Rejoignez")
        reponse = invite.post(reverse("invitation", args=[lien]), {
            "prenom": "Nina", "nom": "Louis", "username": "ninalouis", "mot_de_passe": "Choisi!Par2026",
        })
        self.assertRedirects(reponse, reverse("tableau_de_bord"), fetch_redirect_response=False)
        utilisateur = Utilisateur.objects.get(email="nouveau@exemple.com")
        self.assertTrue(utilisateur.check_password("Choisi!Par2026"))
        self.assertTrue(utilisateur.email_verifie)
        appartenance = Appartenance.sans_filtre.get(utilisateur=utilisateur)
        self.assertEqual((appartenance.etablissement, appartenance.role), (self.m["etab"], self.role_ens))
        invitation.refresh_from_db()
        self.assertEqual(invitation.statut, "ACCEPTEE")
        # le lien ne sert qu'une fois
        self.assertEqual(self.client_class().get(reverse("invitation", args=[lien])).status_code, 410)

    def test_utilisateur_existant_accepte_avec_son_compte(self):
        existant = Utilisateur.objects.create_user("ex", "ex@exemple.com", "MotDePasse!2026")
        self.inviter("ex@exemple.com")
        jeton = Invitation.sans_filtre.get(email="ex@exemple.com").jeton
        invite = self.client_class()
        self.assertContains(invite.get(reverse("invitation", args=[jeton])), "Un compte existe déjà")
        invite.force_login(existant)
        invite.post(reverse("invitation", args=[jeton]))
        self.assertTrue(Appartenance.sans_filtre.filter(utilisateur=existant, etablissement=self.m["etab"]).exists())

    def test_l_invitation_est_liee_a_l_adresse_invitee(self):
        self.inviter()
        invitation = Invitation.sans_filtre.get(email="nouveau@exemple.com")
        intrus = Utilisateur.objects.create_user("i", "intrus@exemple.com", "MotDePasse!2026")
        with self.assertRaises(ErreurMetier):
            saas.accepter_invitation(invitation, intrus)
        client = self.client_class()
        client.force_login(intrus)
        client.post(reverse("invitation", args=[invitation.jeton]))
        self.assertFalse(Appartenance.sans_filtre.filter(utilisateur=intrus, etablissement=self.m["etab"]).exists())

    def test_invitation_expiree_ou_revoquee(self):
        self.inviter()
        invitation = Invitation.sans_filtre.get()
        invitation.date_expiration = timezone.now() - timedelta(days=1)
        invitation.save()
        self.assertEqual(self.client_class().get(reverse("invitation", args=[invitation.jeton])).status_code, 410)

    def test_invitation_apprenant_associe_le_compte_au_dossier(self):
        apprenant = apprenants.creer_apprenant(
            self.m["etab"], "Louis", "Nina", "F", date(2013, 5, 1),
            email="nina.apprenant@exemple.com",
        )
        role = Role.sans_filtre.get(etablissement=self.m["etab"], nom="Apprenant")
        reponse = self.client.post(reverse("personnel"), {
            "invitation-email": apprenant.email,
            "invitation-role": role.pk,
            "invitation-apprenant": apprenant.pk,
        })
        self.assertRedirects(reponse, reverse("personnel"), fetch_redirect_response=False)
        invitation = Invitation.sans_filtre.get(email=apprenant.email)
        client = self.client_class()
        client.post(reverse("invitation", args=[invitation.jeton]), {
            "prenom": "Nina", "nom": "Louis", "username": "ninalouis", "mot_de_passe": "Choisi!Par2026",
        })
        apprenant.refresh_from_db()
        self.assertEqual(apprenant.utilisateur.email, apprenant.email)
        self.assertEqual(Appartenance.sans_filtre.get(utilisateur=apprenant.utilisateur).role, role)

    def test_invitation_parent_associe_le_compte_et_protege_l_adresse(self):
        responsable = apprenants.creer_responsable(
            self.m["etab"], "Louis", "Paul", email="parent@exemple.com",
        )
        apprenant = apprenants.creer_apprenant(
            self.m["etab"], "Louis", "Nina", "F", date(2013, 5, 1),
            responsable=responsable,
        )
        role = Role.sans_filtre.get(etablissement=self.m["etab"], nom="Parent")
        reponse = self.client.post(reverse("personnel"), {
            "invitation-email": responsable.email,
            "invitation-role": role.pk,
            "invitation-responsable": responsable.pk,
        })
        self.assertRedirects(reponse, reverse("personnel"), fetch_redirect_response=False)
        invitation = Invitation.sans_filtre.get(email=responsable.email)
        client = self.client_class()
        client.post(reverse("invitation", args=[invitation.jeton]), {
            "prenom": "Paul", "nom": "Louis", "username": "paullouis", "mot_de_passe": "Choisi!Par2026",
        })
        responsable.refresh_from_db()
        self.assertEqual(responsable.utilisateur.email, responsable.email)
        self.assertEqual(responsable.liens_apprenants.get(apprenant=apprenant).apprenant, apprenant)
        self.assertEqual(Appartenance.sans_filtre.get(utilisateur=responsable.utilisateur).role, role)
        invitation.date_expiration = timezone.now() + timedelta(days=1)
        invitation.save()
        self.client.post(reverse("invitation_action", args=[invitation.pk]), {"action": "revoquer"})
        self.assertEqual(self.client_class().get(reverse("invitation", args=[invitation.jeton])).status_code, 410)

    def test_doublons_et_membres_existants_refuses(self):
        self.inviter()
        reponse = self.inviter()
        self.assertContains(reponse, "déjà en attente")
        reponse = self.inviter(self.m["prof"].utilisateur.email)
        self.assertContains(reponse, "fait déjà partie")
        self.assertEqual(Invitation.sans_filtre.count(), 1)

    def test_seul_un_administrateur_peut_inviter(self):
        client = self.client_class()
        client.force_login(self.m["prof"].utilisateur)
        self.assertEqual(client.get(reverse("personnel")).status_code, 403)
        self.assertEqual(client.post(reverse("personnel"), {"invitation-email": "x@x.test", "invitation-role": self.role_ens.pk}).status_code, 403)

    def test_role_d_un_autre_etablissement_refuse(self):
        autre_role = Appartenance.sans_filtre.get(etablissement__nom="Autre école").role
        with self.assertRaises(ErreurMetier):
            saas.inviter(self.m["etab"], "z@z.test", autre_role, self.directeur.utilisateur, "http://t")

    def test_dernier_administrateur_protege(self):
        tableau = Appartenance.sans_filtre.get(etablissement__nom="Autre école")
        with self.assertRaises(ErreurMetier):
            saas.basculer_membre(tableau, False, tableau.utilisateur)
        with self.assertRaises(ErreurMetier):
            saas.changer_role_membre(tableau, tableau.role.__class__.sans_filtre.get(etablissement=tableau.etablissement, nom="Directeur"), tableau.utilisateur)

    def test_changement_de_role_et_desactivation_par_l_interface(self):
        prof = self.m["prof"]
        secretaire_role = self.m["secretaire"].role
        self.client.post(reverse("membre_action", args=[prof.pk]), {"action": "role", "role": secretaire_role.pk})
        prof.refresh_from_db()
        self.assertEqual(prof.role, secretaire_role)
        self.client.post(reverse("membre_action", args=[prof.pk]), {"action": "desactiver"})
        prof.refresh_from_db()
        self.assertFalse(prof.actif)
        client = self.client_class()
        client.force_login(prof.utilisateur)
        self.assertRedirects(client.get(reverse("tableau_de_bord")), reverse("etablissements"))


class TestsAbonnements(TestCase):
    def setUp(self):
        self.m = monde_scolaire("École Abo")
        self.admin = Utilisateur.objects.create_user("adm", "adm@x.test", "MotDePasse!2026")
        saas.creer_espace(self.admin, "Mon espace", "SCOLAIRE")

    def test_essai_gratuit_au_depart(self):
        abonnement = self.m["etab"].abonnement
        self.assertEqual((abonnement.statut, abonnement.plan.code), ("ESSAI", "ESSAI"))
        self.assertEqual(abonnement.date_fin_essai, timezone.localdate() + timedelta(days=saas.DUREE_ESSAI_JOURS))
        self.assertTrue(saas.etat_abonnement(self.m["etab"])[0])

    def test_fin_essai_ne_peut_pas_preceder_le_debut(self):
        abonnement = self.m["etab"].abonnement
        abonnement.date_fin_essai = abonnement.date_debut - timedelta(days=1)
        with self.assertRaises(ValidationError):
            abonnement.save()

    def test_evenement_paiement_refuse_un_abonnement_d_un_autre_etablissement(self):
        autre = monde_scolaire("Autre établissement")
        evenement = EvenementPaiement(
            etablissement=self.m["etab"],
            abonnement=autre["etab"].abonnement,
            fournisseur="test",
            identifiant_externe="evt-test",
            type_evenement=EvenementPaiement.Type.PAIEMENT_REUSSI,
        )
        with self.assertRaises(ValidationError):
            evenement.save()

    def test_quota_d_apprenants_du_plan(self):
        Plan.objects.filter(code="ESSAI").update(limite_apprenants=2)
        from datetime import date

        for nom in ("A", "B"):
            apprenants.creer_apprenant(self.m["etab"], nom, "X", "M", date(2013, 1, 1))
        with self.assertRaises(ErreurMetier) as ctx:
            apprenants.creer_apprenant(self.m["etab"], "C", "X", "M", date(2013, 1, 1))
        self.assertIn("limite du plan", str(ctx.exception))
        saas.modifier_abonnement(self.m["etab"], code_plan="PREMIUM", statut="ACTIF")
        apprenants.creer_apprenant(self.m["etab"], "C", "X", "M", date(2013, 1, 1))

    def test_quota_de_membres_pour_les_invitations(self):
        Plan.objects.filter(code="ESSAI").update(limite_membres=4)  # 3 membres déjà présents
        directeur = self.m["directeur"]
        saas.inviter(self.m["etab"], "un@x.test", self.m["prof"].role, directeur.utilisateur, "http://t")
        with self.assertRaises(ErreurMetier):
            saas.inviter(self.m["etab"], "deux@x.test", self.m["prof"].role, directeur.utilisateur, "http://t")

    def test_etablissement_suspendu_ou_essai_termine_est_bloque(self):
        self.client.force_login(self.m["directeur"].utilisateur)
        self.assertEqual(self.client.get(reverse("tableau_de_bord")).status_code, 200)
        saas.modifier_abonnement(self.m["etab"], statut="SUSPENDU")
        reponse = self.client.get(reverse("tableau_de_bord"))
        self.assertEqual(reponse.status_code, 402)
        self.assertContains(reponse, "suspendu", status_code=402)
        self.assertEqual(self.client.get(reverse("apprenants:liste")).status_code, 402)
        self.assertEqual(self.client.get(reverse("abonnement")).status_code, 200)  # reste accessible
        saas.modifier_abonnement(self.m["etab"], statut="ESSAI")
        Abonnement.objects.filter(etablissement=self.m["etab"]).update(date_fin_essai=timezone.localdate() - timedelta(days=1))
        self.assertEqual(self.client.get(reverse("tableau_de_bord")).status_code, 402)
        saas.modifier_abonnement(self.m["etab"], statut="ACTIF")
        self.assertEqual(self.client.get(reverse("tableau_de_bord")).status_code, 200)

    def test_console_de_la_plateforme(self):
        self.client.force_login(self.m["directeur"].utilisateur)
        self.assertEqual(self.client.get(reverse("plateforme")).status_code, 403)
        racine = Utilisateur.objects.create_superuser("root", "root@x.test", "MotDePasse!2026")
        self.client.force_login(racine)
        reponse = self.client.get(reverse("plateforme"))
        self.assertContains(reponse, "École Abo")
        self.assertContains(reponse, "Pilotage de la plateforme")
        self.assertContains(reponse, 'href="/administration/"')
        self.assertContains(reponse, "Administration Django")
        self.client.post(reverse("plateforme_action", args=[self.m["etab"].pk]), {"plan": "STANDARD", "statut": "ACTIF"})
        abonnement = Abonnement.objects.get(etablissement=self.m["etab"])
        self.assertEqual((abonnement.plan.code, abonnement.statut), ("STANDARD", "ACTIF"))
        # A platform administrator without a tenant membership cannot open school workflows.
        saas.modifier_abonnement(self.m["etab"], statut="SUSPENDU")
        self.assertEqual(self.client.get(reverse("tableau_de_bord")).status_code, 302)
        self.assertEqual(self.client.get(reverse("academique:annees")).status_code, 403)

    def test_superutilisateur_configure_la_marque_globale_de_l_erp(self):
        racine = Utilisateur.objects.create_superuser("racine_marque", "racine@x.test", "MotDePasse!2026")
        self.client.force_login(racine)
        page = self.client.get(reverse("configuration_plateforme"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Votre marque dans l’ERP")
        self.assertContains(page, 'id="id_nom"')
        self.assertContains(page, 'data-apercu-nom')
        self.assertContains(page, "configuration_plateforme.js")
        self.assertContains(page, "pied-plateforme__contact")
        self.assertContains(page, "navigation-mobile--plateforme")
        self.assertContains(page, "panneauPlateformeMobile")
        self.assertContains(page, "Journal d’audit")
        self.assertContains(page, "Restons en contact")
        reponse = self.client.post(reverse("configuration_plateforme"), {
            "nom": "Nova Scolaire",
            "nom_court": "Nova",
            "slogan": "Apprendre ensemble",
            "telephone": "+509 1234 5678",
            "email": "contact@nova.test",
            "adresse": "Port-au-Prince",
            "site_web": "https://nova.test/",
            "linkedin_url": "https://www.linkedin.com/company/nova-test/",
            "facebook_url": "https://www.facebook.com/nova-test/",
            "instagram_url": "https://www.instagram.com/nova-test/",
            "pied_de_page": "Une plateforme au service des écoles.",
        })
        self.assertRedirects(reponse, reverse("configuration_plateforme"))
        self.assertEqual(ConfigurationPlateforme.objects.get().nom, "Nova Scolaire")
        self.assertEqual(
            ConfigurationPlateforme.objects.get().linkedin_url,
            "https://www.linkedin.com/company/nova-test/",
        )
        self.client.logout()
        public = self.client.get(reverse("accueil_public"))
        self.assertContains(public, "Nova")
        self.assertContains(public, "Apprendre ensemble")
        self.assertContains(public, "contact@nova.test")
        self.assertContains(public, "https://www.linkedin.com/company/nova-test/")
        self.assertContains(public, "https://www.facebook.com/nova-test/")
        self.assertContains(public, "https://www.instagram.com/nova-test/")
        self.assertContains(public, "Une plateforme au service des écoles.")

    def test_console_provisionne_un_espace_et_trace_le_superuser(self):
        administrateur = Utilisateur.objects.create_user(
            "admin_espace", "admin_espace@x.test", "MotDePasse!2026"
        )
        superuser = Utilisateur.objects.create_superuser(
            "maitre", "maitre@x.test", "MotDePasse!2026"
        )
        self.client.force_login(superuser)

        page = self.client.get(reverse("plateforme"))
        self.assertContains(page, "Provisionner un établissement")
        self.assertContains(page, "Activité d'audit récente")
        self.assertContains(page, "Membres actifs")
        self.assertContains(page, '<option value="SCOLAIRE">')
        self.assertContains(page, '<option value="UNIVERSITAIRE">')
        self.assertContains(page, '<option value="PROFESSIONNEL">')
        reponse = self.client.post(reverse("plateforme"), {
            "action": "creer",
            "provisionnement-nom_etablissement": "Nouvel établissement",
            "provisionnement-type_etablissement": "UNIVERSITAIRE",
            "provisionnement-administrateur": administrateur.pk,
        })

        self.assertRedirects(reponse, reverse("plateforme"))
        etablissement = Etablissement.objects.get(nom="Nouvel établissement")
        appartenance = Appartenance.sans_filtre.get(etablissement=etablissement)
        self.assertEqual(appartenance.utilisateur, administrateur)
        self.assertEqual(etablissement.abonnement.statut, Abonnement.Statut.ESSAI)
        self.assertTrue(
            JournalAudit.objects.filter(
                etablissement=etablissement, utilisateur=superuser, action="espace.creation"
            ).exists()
        )

    def test_console_change_etat_tenant_et_refuse_un_plan_invalide(self):
        superuser = Utilisateur.objects.create_superuser(
            "maitre_etat", "maitre_etat@x.test", "MotDePasse!2026"
        )
        self.client.force_login(superuser)
        etablissement = self.m["etab"]

        self.client.post(reverse("plateforme_action", args=[etablissement.pk]), {
            "actif": "0", "plan": "INEXISTANT", "statut": "ACTIF",
        })
        etablissement.refresh_from_db()
        self.assertTrue(etablissement.actif)
        self.assertEqual(etablissement.abonnement.statut, Abonnement.Statut.ESSAI)

        self.client.post(reverse("plateforme_action", args=[etablissement.pk]), {"actif": "0"})
        etablissement.refresh_from_db()
        self.assertFalse(etablissement.actif)
        self.assertTrue(
            JournalAudit.objects.filter(
                etablissement=etablissement, utilisateur=superuser, action="espace.suspension"
            ).exists()
        )

    def test_parametres_reserves_a_l_administrateur(self):
        client = self.client_class()
        client.force_login(self.admin)
        etab = Etablissement.objects.get(nom="Mon espace")
        client.post(reverse("parametres"), {"cible": "notation", "notation-seuil_reussite_pct": "60", "notation-echelle_moyenne": "10", "notation-classement_autorise": "on"})
        parametres = etab.parametres
        parametres.refresh_from_db()
        self.assertEqual((int(parametres.seuil_reussite_pct), parametres.echelle_moyenne, parametres.classement_autorise), (60, 10, True))
        client.post(reverse("parametres"), {
            "cible": "identite", "identite-nom": "Collège Éducation Moderne",
            "identite-nom_court": "CEMO", "identite-slogan": "Réussir ensemble",
            "identite-telephone": "+509 0000-0000", "identite-email": "contact@cemo.ht",
            "identite-adresse": "Port-au-Prince", "identite-site_web": "https://cemo.ht",
        })
        etab.refresh_from_db()
        self.assertEqual(etab.nom, "Collège Éducation Moderne")
        self.assertEqual(etab.nom_court, "CEMO")
        self.assertEqual(etab.slogan, "Réussir ensemble")
        self.assertEqual(etab.telephone, "+509 0000-0000")
        self.assertEqual(etab.email, "contact@cemo.ht")
        self.assertEqual(etab.adresse, "Port-au-Prince")
        self.assertEqual(etab.site_web, "https://cemo.ht")
        self.assertContains(client.get(reverse("parametres")), "Nom court / sigle")
        reponse = client.post(reverse("parametres"), {
            "cible": "periodes", "periodes-nombre_periodes_par_annee": "5",
        })
        self.assertRedirects(reponse, reverse("parametres"))
        etab.parametres.refresh_from_db()
        self.assertEqual(etab.parametres.nombre_periodes_par_annee, 5)
        self.client.force_login(self.m["prof"].utilisateur)
        self.assertEqual(self.client.get(reverse("parametres")).status_code, 403)

    def test_parametres_enregistrent_langue_et_fuseau_horaire(self):
        client = self.client_class()
        client.force_login(self.admin)
        etab = Etablissement.objects.get(nom="Mon espace")
        reponse = client.post(reverse("parametres"), {
            "cible": "identite",
            "identite-nom": etab.nom,
            "identite-devise": etab.devise,
            "identite-langue": "es",
            "identite-fuseau_horaire": "America/New_York",
        })
        self.assertRedirects(reponse, reverse("parametres"))
        etab.refresh_from_db()
        self.assertEqual((etab.langue, etab.fuseau_horaire), ("es", "America/New_York"))

    def test_formulaire_identite_rejette_un_fuseau_inconnu(self):
        formulaire = FormulaireIdentite(
            {"nom": "École", "type": "SCOLAIRE", "langue": "fr", "fuseau_horaire": "Mars/Olympus"},
            instance=Etablissement(nom="École", type="SCOLAIRE", langue="fr"),
        )
        self.assertFalse(formulaire.is_valid())
        self.assertIn("fuseau_horaire", formulaire.errors)

    def test_langue_de_session_peut_remplacer_puis_retablir_la_langue_de_l_ecole(self):
        client = self.client_class()
        client.force_login(self.admin)
        page = client.get(reverse("tableau_de_bord"))
        self.assertEqual(page["Content-Language"], "fr")
        self.assertContains(page, 'id="selecteurLangue"')
        self.assertNotContains(page, "Langue de l’établissement")
        self.assertNotContains(page, ">Appliquer</button>", html=False)
        self.assertContains(page, "js/interface.js?v=2")
        client.post(reverse("choisir_langue"), {"langue": "en", "next": reverse("tableau_de_bord")})
        self.assertEqual(client.get(reverse("tableau_de_bord"))["Content-Language"], "en")
        client.post(reverse("choisir_langue"), {"langue": "", "next": reverse("tableau_de_bord")})
        self.assertEqual(client.get(reverse("tableau_de_bord"))["Content-Language"], "fr")


    def test_vocabulaire_configurable(self):
        client = self.client_class()
        client.force_login(self.admin)
        champs = {f"vocabulaire-{cle}_{f}": v for cle, (s, p) in {"periode": ("Trimestre", "Trimestres"), "niveau": ("Classe de niveau", "Classes de niveau"), "classe": ("Section", "Sections")}.items() for f, v in (("singulier", s), ("pluriel", p))}
        client.post(reverse("parametres"), {"cible": "vocabulaire", **champs})
        from applications.noyau.services import vocabulaire

        etab = Etablissement.objects.get(nom="Mon espace")
        self.assertEqual(vocabulaire(etab, "classe"), "Section")


class TestsMiddlewareLocalisation(TestCase):
    def test_langue_et_fuseau_du_tenant_sont_isoles_et_restaures(self):
        requete = RequestFactory().get("/")
        requete.session = {}
        requete.etablissement = SimpleNamespace(langue="es", fuseau_horaire="America/Los_Angeles")

        def reponse_locale(request):
            date_locale = timezone.localtime(
                datetime(2026, 1, 1, 1, tzinfo=datetime_timezone.utc)
            ).date()
            return HttpResponse(
                f"{translation.get_language()}|{timezone.get_current_timezone_name()}|{date_locale}"
            )

        middleware = MiddlewareLocalisation(reponse_locale)
        reponse = middleware(requete)
        self.assertEqual(reponse.content.decode(), "es|America/Los_Angeles|2025-12-31")
        self.assertEqual(reponse["Content-Language"], "es")
        self.assertIn("Cookie", reponse["Vary"])
        self.assertNotEqual(timezone.get_current_timezone_name(), "America/Los_Angeles")


class TestsMotDePasse(TestCase):
    def test_reinitialisation_par_e_mail(self):
        Utilisateur.objects.create_user("u", "oubli@exemple.com", "AncienMdp!2026")
        self.client.post(reverse("mot_de_passe_oublie"), {"email": "oubli@exemple.com"})
        self.assertEqual(len(mail.outbox), 1)
        lien = re.search(r"http://testserver(/mot-de-passe/reinitialiser/[^\s]+)", mail.outbox[0].body).group(1)
        reponse = self.client.get(lien, follow=True)
        formulaire_url = reponse.request["PATH_INFO"]
        self.client.post(formulaire_url, {"new_password1": "NouveauMdp!2026", "new_password2": "NouveauMdp!2026"})
        self.assertTrue(self.client.login(username="oubli@exemple.com", password="NouveauMdp!2026"))

    def test_changement_depuis_le_profil(self):
        u = Utilisateur.objects.create_user("v", "chg@exemple.com", "AncienMdp!2026")
        self.client.force_login(u)
        self.client.post(reverse("mot_de_passe_changer"), {"old_password": "AncienMdp!2026", "new_password1": "Autre!Mdp2026", "new_password2": "Autre!Mdp2026"})
        u.refresh_from_db()
        self.assertTrue(u.check_password("Autre!Mdp2026"))
