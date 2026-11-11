from django.contrib import admin

from .models import AffectationPaiement, Remboursement


@admin.register(AffectationPaiement)
class AffectationPaiementAdmin(admin.ModelAdmin):
    list_display = ("paiement", "echeance", "montant")
    readonly_fields = ("paiement", "echeance", "montant")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Remboursement)
class RemboursementAdmin(admin.ModelAdmin):
    list_display = ("paiement", "montant", "date_remboursement", "effectue_par")
    readonly_fields = ("paiement", "montant", "motif", "date_remboursement", "effectue_par")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
