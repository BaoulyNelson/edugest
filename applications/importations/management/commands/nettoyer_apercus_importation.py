from django.core.management.base import BaseCommand

from applications.importations.services import nettoyer_apercus_expires


class Command(BaseCommand):
    help = "Supprime les données personnelles des aperçus d'importation expirés."

    def handle(self, *args, **options):
        nombre = nettoyer_apercus_expires()
        self.stdout.write(self.style.SUCCESS(f"{nombre} aperçu(s) nettoyé(s)."))
