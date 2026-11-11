from django.contrib import admin

from .models import (
    Apprenant, DecisionInscription, IncidentDisciplinaire, Inscription,
    LienResponsable, PieceInscription, ResponsableLegal,
)

admin.site.register([
    Apprenant, ResponsableLegal, LienResponsable, Inscription,
    DecisionInscription, PieceInscription, IncidentDisciplinaire,
])
