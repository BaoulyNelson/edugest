from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Abonnement, Appartenance, ConfigurationPlateforme, Etablissement, EvenementPaiement,
    Invitation, JournalAudit, Plan, ParametresEtablissement, Role, UsageAbonnement,
    Utilisateur, VocabulaireInstitutionnel,
)


@admin.register(Utilisateur)
class AdministrationUtilisateur(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "is_staff")


@admin.register(Etablissement)
class AdministrationEtablissement(admin.ModelAdmin):
    list_display = ("nom", "type", "actif")


@admin.register(JournalAudit)
class AdministrationJournal(admin.ModelAdmin):
    list_display = ("date", "etablissement", "utilisateur", "action", "objet_type", "objet_id")
    list_filter = ("action", "etablissement")
    readonly_fields = [f.name for f in JournalAudit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfigurationPlateforme)
class AdministrationConfigurationPlateforme(admin.ModelAdmin):
    list_display = ("nom", "email", "modifie_le")

    def has_add_permission(self, request):
        return not ConfigurationPlateforme.objects.filter(pk=1).exists()

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([Plan, Abonnement, Invitation, Role, Appartenance, ParametresEtablissement, VocabulaireInstitutionnel])


@admin.register(EvenementPaiement)
class AdministrationEvenementPaiement(admin.ModelAdmin):
    list_display = ("etablissement", "fournisseur", "identifiant_externe", "type_evenement", "recu_le")
    list_filter = ("fournisseur", "type_evenement", "etablissement")
    readonly_fields = [f.name for f in EvenementPaiement._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UsageAbonnement)
class AdministrationUsageAbonnement(admin.ModelAdmin):
    list_display = ("etablissement", "date", "nombre_apprenants", "nombre_membres", "invitations_en_attente")
    list_filter = ("date", "etablissement")
    readonly_fields = [f.name for f in UsageAbonnement._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
