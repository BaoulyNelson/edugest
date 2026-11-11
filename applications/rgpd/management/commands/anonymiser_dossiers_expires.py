from django.core.management.base import BaseCommand

from applications.noyau.models import Etablissement
from applications.rgpd import services


class Command(BaseCommand):
    help = "Liste les dossiers expirés ou les anonymise avec --appliquer."

    def add_arguments(self, parser):
        parser.add_argument("--appliquer", action="store_true")
        parser.add_argument("--etablissement-id", type=int)

    def handle(self, *args, **options):
        etablissements = Etablissement.objects.filter(actif=True)
        if options["etablissement_id"]:
            etablissements = etablissements.filter(pk=options["etablissement_id"])
        candidats = []
        for etablissement in etablissements:
            candidats.extend(services.dossiers_a_anonymiser(etablissement))
        if not options["appliquer"]:
            self.stdout.write(f"{len(candidats)} dossier(s) à anonymiser. Relancez avec --appliquer.")
            return
        for apprenant in candidats:
            services.anonymiser_apprenant(apprenant, None)
        self.stdout.write(self.style.SUCCESS(f"{len(candidats)} dossier(s) anonymisé(s)."))
