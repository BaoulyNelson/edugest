from django.contrib import admin

from .models import (
    AffectationEnseignant, ChoixQuestion, DerogationClasse, Matiere,
    MatiereNiveau, QuestionQuiz, Quiz, ReponseQuiz, RessourcePedagogique,
    TentativeQuiz,
)

admin.site.register([Matiere, MatiereNiveau, DerogationClasse, AffectationEnseignant])
admin.site.register([
    RessourcePedagogique, Quiz, QuestionQuiz, ChoixQuestion, TentativeQuiz, ReponseQuiz,
])
