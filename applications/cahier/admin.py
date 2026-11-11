from django.contrib import admin

from .models import (
    Devoir, EntreeCahier, NotificationCahier, PieceJointeDevoir, PieceJointeRemise, Remise,
)


@admin.register(EntreeCahier)
class AdministrationEntreeCahier(admin.ModelAdmin):
    list_display = ("date", "titre", "classe", "matiere_niveau", "enseignant")
    list_filter = ("date", "classe__annee")


@admin.register(Devoir)
class AdministrationDevoir(admin.ModelAdmin):
    list_display = ("titre", "classe", "matiere_niveau", "date_limite", "heure_limite", "bareme", "enseignant")
    list_filter = ("date_limite", "classe__annee")


@admin.register(Remise)
class AdministrationRemise(admin.ModelAdmin):
    list_display = ("devoir", "inscription", "remise_le", "en_retard", "note", "corrige_le")
    list_filter = ("en_retard",)


admin.site.register(PieceJointeDevoir)
admin.site.register(PieceJointeRemise)
admin.site.register(NotificationCahier)
