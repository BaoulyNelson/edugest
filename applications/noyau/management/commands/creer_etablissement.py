"""Crée un établissement avec ses rôles par défaut et son administrateur."""
from django.core.management.base import BaseCommand, CommandError

from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import TypeEtablissement
from applications.noyau.services import creer_etablissement, creer_membre


class Command(BaseCommand):
    help = "Crée un établissement et son administrateur."

    def add_arguments(self, parser):
        parser.add_argument("--nom", required=True)
        parser.add_argument("--type", choices=[type_.value for type_ in TypeEtablissement],
                            default=TypeEtablissement.SCOLAIRE)
        parser.add_argument("--administrateur", required=True, help="Identifiant de connexion de l'administrateur")
        parser.add_argument("--email", required=True)
        parser.add_argument("--mot-de-passe", required=True, dest="mot_de_passe")

    def handle(self, *args, **options):
        try:
            etablissement = creer_etablissement(options["nom"], TypeEtablissement(options["type"]))
            creer_membre(
                etablissement, options["administrateur"], options["email"], options["mot_de_passe"],
                "Administrateur de l'établissement",
            )
        except ErreurMetier as erreur:
            raise CommandError(str(erreur))
        self.stdout.write(self.style.SUCCESS(f"Établissement « {etablissement} » créé."))
