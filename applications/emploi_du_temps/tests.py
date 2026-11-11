from datetime import datetime, time

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from applications.apprenants.models import LienResponsable, ResponsableLegal
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.outils_tests import inscrire, monde_scolaire
from applications.noyau.services import creer_membre
from applications.pedagogie.services import affecter_enseignant

from . import services
from .models import Creneau, Salle


class TestsEmploiDuTemps(TestCase):
    def setUp(self):
        self.monde = monde_scolaire()
        self.salle = Salle.objects.create(
            etablissement=self.monde["etab"], nom="Salle 1", capacite=30,
        )
        self.autre_prof = creer_membre(
            self.monde["etab"], "prof_edt_2", "prof-edt-2@ecole.test",
            "MotDePasse!2026", "Enseignant",
        )
        self.affectation = self.monde["affectation"]
        self.affectation_b = affecter_enseignant(
            self.monde["prof"], self.monde["mn"], self.monde["classe_b"],
        )
        self.affectation_a_autre = affecter_enseignant(
            self.autre_prof, self.monde["mn"], self.monde["classe_a"],
        )
        self.affectation_b_autre = affecter_enseignant(
            self.autre_prof, self.monde["mn"], self.monde["classe_b"],
        )

    def creer(self, affectation, debut="08:00", fin="09:00", jour=1, salle=None):
        return services.creer_creneau(
            etablissement=self.monde["etab"],
            affectation=affectation,
            jour=jour,
            heure_debut=time.fromisoformat(debut),
            heure_fin=time.fromisoformat(fin),
            salle=salle,
            acteur=self.monde["directeur"].utilisateur,
        )

    def test_conflits_de_classe_enseignant_et_salle(self):
        self.creer(self.affectation, salle=self.salle)
        with self.assertRaises(ErreurMetier) as conflit_classe:
            self.creer(self.affectation_a_autre, "08:30", "09:30")
        self.assertIn("classe", str(conflit_classe.exception))

        with self.assertRaises(ErreurMetier) as conflit_enseignant:
            self.creer(self.affectation_b, "08:30", "09:30")
        self.assertIn("enseigne déjà", str(conflit_enseignant.exception))

        with self.assertRaises(ErreurMetier) as conflit_salle:
            self.creer(self.affectation_b_autre, "08:30", "09:30", salle=self.salle)
        self.assertIn("salle", str(conflit_salle.exception))

    def test_creneaux_contigus_et_jours_differents_sont_autorises(self):
        self.creer(self.affectation, "08:00", "09:00")
        self.creer(self.affectation, "09:00", "10:00")
        self.creer(self.affectation, "08:00", "09:00", jour=2)
        self.assertEqual(Creneau.objects.count(), 3)

    def test_horaires_incoherents_et_salle_trop_petites_refuses(self):
        with self.assertRaises(ErreurMetier):
            self.creer(self.affectation, "10:00", "09:00")
        petite = Salle.objects.create(
            etablissement=self.monde["etab"], nom="Petite salle", capacite=1,
        )
        inscrire(self.monde, "Premier élève")
        inscrire(self.monde, "Deuxième élève")
        with self.assertRaises(ErreurMetier):
            self.creer(self.affectation, "11:00", "12:00", salle=petite)

    def test_seance_en_cours_est_calculee_en_heure_locale(self):
        self.creer(self.affectation, "08:00", "09:00", jour=1)
        lundi_8h30 = timezone.make_aware(datetime(2026, 11, 2, 8, 30))
        lignes = services.regrouper_par_jour(
            services.creneaux_de_classe(self.monde["classe_a"]), lundi_8h30,
        )
        self.assertTrue(lignes[0]["aujourdhui"])
        self.assertTrue(lignes[0]["seances"][0]["en_cours"])

    def test_vues_gestionnaire_enseignant_parent_et_eleve(self):
        self.creer(self.affectation, salle=self.salle)
        inscription = inscrire(self.monde, "Élève emploi")
        eleve = creer_membre(
            self.monde["etab"], "eleve_edt", "eleve-edt@ecole.test",
            "MotDePasse!2026", "Apprenant",
        )
        inscription.apprenant.utilisateur = eleve.utilisateur
        inscription.apprenant.save(update_fields=["utilisateur"])
        parent = creer_membre(
            self.monde["etab"], "parent_edt", "parent-edt@ecole.test",
            "MotDePasse!2026", "Parent",
        )
        responsable = ResponsableLegal.objects.create(
            etablissement=self.monde["etab"],
            nom="Responsable emploi",
            utilisateur=parent.utilisateur,
        )
        LienResponsable.objects.create(
            etablissement=self.monde["etab"],
            apprenant=inscription.apprenant,
            responsable=responsable,
        )

        self.client.force_login(self.monde["directeur"].utilisateur)
        self.assertContains(self.client.get(reverse("emploi_du_temps:gestion")), "Salle 1")
        self.client.force_login(self.monde["prof"].utilisateur)
        self.assertEqual(self.client.get(reverse("emploi_du_temps:gestion")).status_code, 403)
        self.assertContains(self.client.get(reverse("emploi_du_temps:mon_emploi")), "Mathématiques")
        for utilisateur in (parent.utilisateur, eleve.utilisateur):
            self.client.force_login(utilisateur)
            self.assertContains(self.client.get(reverse("emploi_du_temps:mon_emploi")), "Mathématiques")
