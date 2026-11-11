from datetime import date

from django.test import TestCase
from django.urls import reverse

from applications.academique.services import activer_annee, creer_annee, creer_classe, creer_niveau
from applications.apprenants.models import LienResponsable, ResponsableLegal
from applications.apprenants.services import creer_apprenant, creer_inscription, decider_inscription
from applications.noyau.models import TypeEtablissement
from applications.noyau.services import creer_etablissement, creer_membre
from applications.pedagogie.services import affecter_enseignant, creer_matiere, definir_matiere_niveau
from . import services
from .models import Conversation, NotificationMessage


class TestsMessagerie(TestCase):
    def setUp(self):
        self.etablissement = creer_etablissement("Établissement Messagerie", TypeEtablissement.SCOLAIRE)
        self.annee = creer_annee(
            self.etablissement, "2026-2027", date(2026, 9, 1), date(2027, 6, 30), 3,
        )
        activer_annee(self.annee)
        self.niveau = creer_niveau(self.etablissement, "7e année")
        self.classe_a = creer_classe(self.niveau, self.annee, "7e A")
        self.classe_b = creer_classe(self.niveau, self.annee, "7e B")
        self.matiere = creer_matiere(self.etablissement, "Mathématiques")
        self.matiere_niveau = definir_matiere_niveau(self.annee, self.niveau, self.matiere, 100)
        self.prof = creer_membre(
            self.etablissement, "prof_message", "prof-message@ecole.test",
            "MotDePasse!2026", "Enseignant",
        )
        self.autre_prof = creer_membre(
            self.etablissement, "autre_prof_message", "autre-prof-message@ecole.test",
            "MotDePasse!2026", "Enseignant",
        )
        self.directeur = creer_membre(
            self.etablissement, "directeur_message", "directeur-message@ecole.test",
            "MotDePasse!2026", "Directeur",
        )
        affecter_enseignant(self.prof, self.matiere_niveau, self.classe_a)
        affecter_enseignant(self.autre_prof, self.matiere_niveau, self.classe_b)
        self.parent = creer_membre(
            self.etablissement, "parent_message", "parent-message@ecole.test",
            "MotDePasse!2026", "Parent",
        )
        self.autre_parent = creer_membre(
            self.etablissement, "autre_parent_message", "autre-parent-message@ecole.test",
            "MotDePasse!2026", "Parent",
        )
        self.eleve = creer_membre(
            self.etablissement, "eleve_message", "eleve-message@ecole.test",
            "MotDePasse!2026", "Apprenant",
        )
        self.inscription = self._inscrire("Élève A", self.classe_a, self.parent, self.eleve)
        self.autre_inscription = self._inscrire("Élève B", self.classe_b, self.autre_parent)

    def _inscrire(self, nom, classe, parent, eleve=None):
        apprenant = creer_apprenant(
            self.etablissement, nom, "Test", "M", date(2013, 5, 1),
        )
        if eleve:
            apprenant.utilisateur = eleve.utilisateur
            apprenant.save(update_fields=["utilisateur"])
        inscription = creer_inscription(
            self.etablissement, apprenant, self.niveau, classe=classe,
        )
        decider_inscription(inscription, "VALIDER", self.directeur.utilisateur)
        responsable = ResponsableLegal.objects.create(
            etablissement=self.etablissement,
            nom=f"Responsable {nom}",
            utilisateur=parent.utilisateur,
        )
        LienResponsable.objects.create(
            etablissement=self.etablissement,
            apprenant=apprenant,
            responsable=responsable,
        )
        return inscription

    def connecter(self, appartenance):
        self.client.force_login(appartenance.utilisateur)
        session = self.client.session
        session["etablissement_id"] = self.etablissement.pk
        session.save()

    def test_perimetre_emetteur_famille_enseignant_et_direction(self):
        parent_ids = services.identifiants_autorises(
            self.parent.utilisateur, self.etablissement, self.parent,
        )
        self.assertIn(self.prof.utilisateur_id, parent_ids)
        self.assertIn(self.directeur.utilisateur_id, parent_ids)
        self.assertNotIn(self.autre_prof.utilisateur_id, parent_ids)
        self.assertNotIn(self.autre_parent.utilisateur_id, parent_ids)

        prof_ids = services.identifiants_autorises(
            self.prof.utilisateur, self.etablissement, self.prof,
        )
        self.assertIn(self.parent.utilisateur_id, prof_ids)
        self.assertIn(self.eleve.utilisateur_id, prof_ids)
        self.assertNotIn(self.autre_parent.utilisateur_id, prof_ids)

        direction_ids = services.identifiants_autorises(
            self.directeur.utilisateur, self.etablissement, self.directeur,
        )
        self.assertIn(self.parent.utilisateur_id, direction_ids)
        self.assertIn(self.autre_parent.utilisateur_id, direction_ids)
        self.assertIn(self.prof.utilisateur_id, direction_ids)

    def test_conversation_reponse_et_notifications(self):
        self.connecter(self.parent)
        reponse = self.client.post(reverse("messagerie:nouveau"), {
            "destinataires": [self.prof.utilisateur_id],
            "sujet": "Question sur les devoirs",
            "texte": "Mon enfant a une question.",
        })
        self.assertEqual(reponse.status_code, 302)
        conversation = Conversation.objects.get()
        self.assertEqual(conversation.participants.count(), 2)
        self.assertTrue(NotificationMessage.objects.filter(destinataire=self.prof.utilisateur).exists())

        self.connecter(self.prof)
        self.assertContains(self.client.get(reverse("messagerie:boite")), "Nouveau")
        self.assertContains(self.client.get(reverse("messagerie:conversation", args=[conversation.pk])), "Mon enfant a une question.")
        self.assertFalse(NotificationMessage.objects.filter(destinataire=self.prof.utilisateur, lue=False).exists())
        self.client.post(reverse("messagerie:conversation", args=[conversation.pk]), {
            "texte": "Je répondrai demain.",
        })
        self.connecter(self.parent)
        self.assertContains(self.client.get(reverse("messagerie:boite")), "Nouveau")
        self.assertContains(
            self.client.get(reverse("messagerie:conversation", args=[conversation.pk])),
            "Je répondrai demain.",
        )

    def test_message_hors_perimetre_refuse_et_conversation_privee(self):
        self.connecter(self.parent)
        reponse = self.client.post(reverse("messagerie:nouveau"), {
            "destinataires": [self.autre_parent.utilisateur_id],
            "sujet": "Message interdit",
            "texte": "Bonjour.",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Conversation.objects.exists())

        conversation = services.envoyer(
            self.parent.utilisateur,
            [self.prof.utilisateur],
            "Privé",
            "Secret",
            self.etablissement,
            self.parent,
        )
        self.connecter(self.autre_parent)
        self.assertEqual(
            self.client.get(reverse("messagerie:conversation", args=[conversation.pk])).status_code,
            404,
        )

    def test_diffusion_par_classe_cree_une_conversation_privee_par_famille(self):
        self.connecter(self.prof)
        reponse = self.client.post(reverse("messagerie:nouveau"), {
            "classe": self.classe_a.pk,
            "sujet": "Rappel de classe",
            "texte": "Sortie vendredi.",
        })
        self.assertEqual(reponse.status_code, 302)
        conversations = Conversation.objects.all()
        self.assertEqual(conversations.count(), 2)
        self.assertTrue(all(conversation.participants.count() == 2 for conversation in conversations))
        self.connecter(self.autre_parent)
        self.assertNotContains(self.client.get(reverse("messagerie:boite")), "Rappel de classe")

    def test_marquer_toutes_les_notifications_comme_lues(self):
        services.envoyer(
            self.parent.utilisateur, [self.prof.utilisateur], "Bonjour", "Message",
            self.etablissement, self.parent,
        )
        self.connecter(self.prof)
        notifications = self.client.get(reverse("tableau_de_bord")).context["notifications"]
        self.assertTrue(any(notification["texte"].startswith("Message de") for notification in notifications))
        self.client.post(reverse("messagerie:tout_lu"))
        self.assertEqual(
            NotificationMessage.objects.filter(destinataire=self.prof.utilisateur, lue=False).count(),
            0,
        )
