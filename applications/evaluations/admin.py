from django.contrib import admin

from .models import (
    ComposanteEvaluation, ConfigurationEvaluation, HistoriqueNote, Note, ResultatPeriode,
)

admin.site.register([
    ConfigurationEvaluation, ComposanteEvaluation, Note, HistoriqueNote, ResultatPeriode,
])
