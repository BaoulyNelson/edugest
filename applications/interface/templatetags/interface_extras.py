from django import template
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from applications.evaluations.services import formater
from applications.noyau.decorateurs import a_la_permission

register = template.Library()

STATUTS = {
    "EN_ATTENTE": (_("En attente"), "attente", "bi-hourglass-split"),
    "CORRECTION_DEMANDEE": (_("Correction demandée"), "attention", "bi-pencil"),
    "VALIDEE": (_("Validée"), "succes", "bi-check-circle"),
    "REJETEE": (_("Rejetée"), "danger", "bi-x-circle"),
    "ANNULEE": (_("Annulée"), "neutre", "bi-slash-circle"),
    "REUSSI": (_("Réussi"), "succes", "bi-check-circle"),
    "ECHEC": (_("Échec"), "danger", "bi-x-circle"),
    "INCOMPLET": (_("Incomplet"), "attention", "bi-exclamation-circle"),
    "DISPENSE": (_("Dispensé"), "neutre", "bi-dash-circle"),
    "ACTIVE": (_("Active"), "succes", "bi-play-circle"),
    "PREPARATION": (_("En préparation"), "attente", "bi-hourglass-split"),
    "CLOTUREE": (_("Clôturée"), "neutre", "bi-lock"),
    "A_VENIR": (_("À venir"), "attente", "bi-clock"),
    "OUVERTE": (_("Ouverte"), "succes", "bi-unlock"),
    "BROUILLON": (_("Brouillon"), "attente", "bi-pencil"),
    "VERROUILLEE": (_("Verrouillée"), "neutre", "bi-lock"),
    "RECUE": (_("Reçue"), "attente", "bi-inbox"),
    "ACCEPTEE": (_("Acceptée"), "succes", "bi-check-circle"),
    "REFUSEE": (_("Refusée"), "danger", "bi-x-circle"),
}


@register.simple_tag
def statut(code):
    """Badge de statut : toujours un texte et une icône, jamais la couleur seule."""
    libelle, classe, icone = STATUTS.get(code, (code, "neutre", "bi-circle"))
    return format_html('<span class="badge-statut badge-statut--{}"><i class="bi {}" aria-hidden="true"></i> {}</span>',
                       classe, icone, libelle)


@register.filter
def nombre(valeur):
    return formater(valeur)


@register.filter
def element(dictionnaire, cle):
    return dictionnaire.get(cle) if dictionnaire else None


@register.simple_tag(takes_context=True)
def peut_creer_rapidement(context, cible):
    permission = {
        "apprenant": "apprenants.gerer",
        "responsable": "utilisateurs.gerer",
        "matiere": "pedagogie.gerer",
        "faculte": "academique.gerer",
        "programme": "academique.gerer",
        "niveau": "academique.gerer",
        "classe": "academique.gerer",
        "matiere_niveau": "pedagogie.gerer",
    }.get(cible)
    return bool(permission and a_la_permission(context["request"], permission))


@register.simple_tag
def cle_note(inscription_id, composante_id):
    return f"{inscription_id}_{composante_id}"


@register.filter
def type_widget(champ):
    """Type de widget d'un champ (textarea, checkbox, radio, file, select, input) pour adapter sa présentation."""
    widget = champ.field.widget
    nom = widget.__class__.__name__.lower()
    if "radio" in nom:
        return "radio"
    if "checkbox" in nom and "multiple" not in nom:
        return "checkbox"
    if "textarea" in nom:
        return "textarea"
    if "file" in nom:
        return "file"
    if "select" in nom:
        return "select"
    return "input"
