"""Helpers partagés pour les formulaires HTML de l'interface."""


CIBLES_AJOUT_RAPIDE = {
    "Apprenant": "apprenant",
    "Matiere": "matiere",
    "Faculte": "faculte",
    "Programme": "programme",
    "Niveau": "niveau",
    "Classe": "classe",
    "MatiereNiveau": "matiere_niveau",
    "ResponsableLegal": "responsable",
}


def annoter_relations_ajout_rapide(formulaire):
    """Expose un raccourci de création pour les relations ayant un flux sûr dédié."""
    for champ in formulaire.fields.values():
        queryset = getattr(champ, "queryset", None)
        modele = getattr(queryset, "model", None)
        cible = CIBLES_AJOUT_RAPIDE.get(getattr(modele, "__name__", ""))
        if cible:
            champ.widget.attrs["data-ajout-rapide"] = cible
