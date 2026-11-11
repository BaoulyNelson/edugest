from django.contrib import admin

from .models import TentativeConnexion


@admin.register(TentativeConnexion)
class TentativeConnexionAdmin(admin.ModelAdmin):
    list_display = ("cle", "nombre", "derniere_tentative", "bloquee_jusqua")
    readonly_fields = ("cle", "nombre", "derniere_tentative", "bloquee_jusqua")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
