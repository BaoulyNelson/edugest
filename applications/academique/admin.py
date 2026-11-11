from django.contrib import admin

from .models import (
    AnneeAcademique, Classe, Faculte, Niveau, Periode, PresetAcademique,
    Programme, SiteEtablissement,
)

admin.site.register([
    AnneeAcademique, Periode, Faculte, Programme, Niveau, Classe,
    PresetAcademique, SiteEtablissement,
])
