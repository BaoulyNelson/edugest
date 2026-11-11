from django.contrib import admin

from .models import BadgeGenere


@admin.register(BadgeGenere)
class BadgeGenereAdmin(admin.ModelAdmin):
    list_display = ("type_badge", "inscription", "appartenance", "cree_le", "actif")
    list_filter = ("type_badge", "actif", "cree_le")
    readonly_fields = ("jeton", "cree_le", "genere_par")
    actions = None

    def has_add_permission(self, request):
        return False
