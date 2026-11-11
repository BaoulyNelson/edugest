"""Charge un jeu de données de démonstration (école classique, année active, comptes de test)."""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from applications.academique import services as academique
from applications.apprenants import services as apprenants
from applications.noyau.models import Etablissement, TypeEtablissement
from applications.noyau.services import creer_etablissement, creer_membre
from applications.pedagogie import services as pedagogie

NIVEAUX = [("7e année fondamentale", 100), ("8e année fondamentale", 100), ("9e année fondamentale", 200),
           ("NS1", 200), ("NS2", 300), ("NS3", 300), ("NS4 / Philosophie", 300)]
MATIERES = ["Mathématiques", "Français", "Sciences expérimentales", "Histoire"]
COMPTES = [("directeur", "Directeur"), ("secretaire", "Secrétaire"), ("enseignant", "Enseignant"),
           ("pedagogue", "Responsable pédagogique"), ("comptable", "Comptable")]


class Command(BaseCommand):
    help = "Crée l'école de démonstration « Collège Saint-Louis » avec des comptes de test."

    def add_arguments(self, parser):
        parser.add_argument("--mot-de-passe", default="Demo2026!", dest="mot_de_passe")

    @transaction.atomic
    def handle(self, *args, **options):
        nom = "Collège Saint-Louis (démo)"
        if Etablissement.objects.filter(nom=nom).exists():
            self.stdout.write("La démonstration existe déjà.")
            return
        mdp = options["mot_de_passe"]
        etab = creer_etablissement(nom, TypeEtablissement.SCOLAIRE)
        annee = academique.creer_annee(etab, "2026-2027", date(2026, 9, 1), date(2027, 6, 30), 3)
        academique.activer_annee(annee)
        niveaux = [academique.creer_niveau(etab, n) for n, _ in NIVEAUX]
        academique.creer_classe(niveaux[0], annee, "7e A")
        academique.creer_classe(niveaux[0], annee, "7e B")
        academique.creer_classe(niveaux[1], annee, "8e A")
        for matiere_nom in MATIERES:
            matiere = pedagogie.creer_matiere(etab, matiere_nom)
            for niveau, (_, bareme) in zip(niveaux, NIVEAUX):
                pedagogie.definir_matiere_niveau(annee, niveau, matiere, bareme)
        membres = {cle: creer_membre(etab, f"demo_{cle}", f"{cle}@demo.edugest", mdp, role) for cle, role in COMPTES}
        classe_a = niveaux[0].classes.get(nom="7e A")
        from applications.pedagogie.models import MatiereNiveau

        pedagogie.affecter_enseignant(
            membres["enseignant"], MatiereNiveau.objects.get(niveau=niveaux[0], matiere__nom="Mathématiques"), classe_a
        )
        for nom_apprenant, prenom in [("Joseph", "Marie"), ("Pierre", "Jean"), ("Louis", "Sophie"), ("Charles", "Paul")]:
            apprenant = apprenants.creer_apprenant(etab, nom_apprenant, prenom, "F", date(2013, 3, 14))
            inscription = apprenants.creer_inscription(etab, apprenant, niveaux[0], classe=classe_a)
            apprenants.decider_inscription(inscription, "VALIDER", membres["directeur"].utilisateur)
        self.stdout.write(self.style.SUCCESS(
            f"Démo créée. Comptes : {', '.join('demo_' + c for c, _ in COMPTES)} (mot de passe : {mdp})."))
