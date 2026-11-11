from django.core.management.base import BaseCommand

from applications.noyau.models import Etablissement
from applications.noyau.saas import enregistrer_usage_abonnement


class Command(BaseCommand):
    help = "Enregistre une mesure quotidienne de l'utilisation des abonnements."

    def handle(self, *args, **options):
        etablissements = Etablissement.objects.filter(actif=True).order_by("pk")
        for etablissement in etablissements:
            mesure = enregistrer_usage_abonnement(etablissement)
            self.stdout.write(
                f"{etablissement.slug}: {mesure.nombre_apprenants} apprenant(s), "
                f"{mesure.nombre_membres} membre(s)"
            )
