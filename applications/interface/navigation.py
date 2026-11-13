"""Navigation par rôle : les entrées affichées dépendent des permissions réelles."""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from applications.noyau.services import verifier_permission
from .terminologie import profil_etablissement

# cle, libellé, icône, nom de route, permissions (au moins une ; None = tout utilisateur connecté), catégorie
ENTREES = [
    ("accueil", _("Accueil"), "bi-house-door", "tableau_de_bord", None, _("Général")),
    ("classes", _("Classes"), "bi-collection", "evaluations:classes", ("evaluations.saisir", "resultats.consulter", "resultats.consulter_tous"), _("Enseignement")),
    ("notes", _("Notes"), "bi-pencil-square", "evaluations:mes_evaluations", ("evaluations.saisir",), _("Enseignement")),
    ("resultats", _("Résultats"), "bi-bar-chart-line", "evaluations:resultats", ("resultats.consulter", "resultats.consulter_tous"), _("Enseignement")),
    ("portail", _("Résultats"), "bi-bar-chart-line", "evaluations:portail", ("resultats.consulter_propres", "resultats.consulter_enfants"), _("Enseignement")),
    ("apprenants", _("Apprenants"), "bi-people", "apprenants:liste", ("apprenants.consulter", "apprenants.gerer"), _("Scolarité")),
    ("importations", _("Importer"), "bi-cloud-arrow-up", "importations:accueil", ("importations.apprenants", "importations.personnel"), _("Scolarité")),
    ("inscriptions", _("Inscriptions"), "bi-journal-check", "apprenants:inscriptions", ("inscriptions.enregistrer", "inscriptions.decider"), _("Scolarité")),
    ("admissions", _("Candidatures"), "bi-person-plus", "admissions:liste", ("inscriptions.decider",), _("Scolarité")),
    ("badges", _("Badges"), "bi-person-badge", "badges:liste", ("apprenants.consulter", "apprenants.gerer", "utilisateurs.gerer"), _("Scolarité")),
    ("academique", _("Académique"), "bi-calendar3", "academique:annees", ("academique.gerer",), _("Scolarité")),
    ("structure", _("Structure"), "bi-diagram-3", "academique:structure", ("academique.gerer",), _("Scolarité")),
    ("pedagogie", _("Matières"), "bi-journal-text", "pedagogie:matieres", ("pedagogie.gerer",), _("Pédagogie")),
    ("ressources", _("Ressources et quiz"), "bi-lightbulb", "pedagogie:ressources",
     ("pedagogie.gerer", "cahier.gerer", "cahier.gerer_tous", "cahier.consulter", "devoirs.remettre"), _("Pédagogie")),
    ("affectations", _("Enseignants"), "bi-person-workspace", "pedagogie:affectations", ("pedagogie.gerer",), _("Pédagogie")),
    ("personnel", _("Personnel"), "bi-person-badge", "personnel", ("utilisateurs.gerer",), _("Administration")),
    ("rgpd_gestion", _("Protection des données"), "bi-shield-check", "rgpd:demandes", ("rgpd.gerer",), _("Administration")),
    ("rgpd_portail", _("Mes données"), "bi-person-lock", "rgpd:mes_donnees", ("rgpd.demander",), _("Compte")),
    ("parametres", _("Paramètres"), "bi-gear", "parametres", ("etablissement.configurer",), _("Administration")),
    ("abonnement", _("Abonnement"), "bi-credit-card", "abonnement", ("etablissement.configurer",), _("Administration")),
    ("plateforme", _("Plateforme"), "bi-globe2", "plateforme", ("plateforme.administrer",), _("Administration")),
    ("rapports", _("Rapports"), "bi-graph-up", "rapports", ("statistiques.consulter",), _("Pilotage")),
    ("paiements", _("Paiements"), "bi-cash-coin", "finances:paiements", ("finances.consulter",), _("Finances")),
    ("factures", _("Factures"), "bi-receipt-cutoff", "finances:factures", ("finances.consulter",), _("Finances")),
    ("tarifs", _("Tarifs et échéances"), "bi-list-check", "finances:tarifs", ("finances.gerer",), _("Finances")),
    ("mes_factures", _("Mes factures"), "bi-receipt", "finances:mes_factures", ("finances.consulter_propres",), _("Finances")),
    ("depenses", _("Dépenses"), "bi-receipt", "finances:depenses", ("finances.consulter",), _("Finances")),
    ("rapports_financiers", _("Rapports"), "bi-graph-up", "finances:rapports", ("finances.consulter",), _("Finances")),
    ("presence_appel", _("Faire l'appel"), "bi-person-check", "presences:appel", ("presences.saisir",), _("Vie scolaire")),
    ("presence_historique", _("Présences"), "bi-clipboard-data", "presences:liste", ("presences.consulter",), _("Vie scolaire")),
    ("presence_portail", _("Mes absences"), "bi-calendar2-x", "presences:mes_absences", ("presences.consulter_propres",), _("Vie scolaire")),
    ("cahier", _("Cahier de textes"), "bi-journal-bookmark", "cahier:mon_cahier", ("cahier.consulter",), _("Vie scolaire")),
    ("cahier_gerer", _("Séances du cahier"), "bi-journal-bookmark", "cahier:entrees", ("cahier.gerer", "cahier.gerer_tous"), _("Vie scolaire")),
    ("devoirs_gerer", _("Devoirs"), "bi-clipboard-check", "cahier:devoirs", ("cahier.gerer", "cahier.gerer_tous"), _("Vie scolaire")),
    ("messages", _("Messages"), "bi-chat-dots", "messagerie:boite", ("messagerie.utiliser",), _("Communication")),
    ("emploi", _("Emploi du temps"), "bi-calendar-week", "emploi_du_temps:gestion", ("emploi.voir",), _("Vie scolaire")),
    ("emploi_portail", _("Mon emploi du temps"), "bi-calendar-week", "emploi_du_temps:mon_emploi", ("emploi.enseigner", "emploi.consulter"), _("Vie scolaire")),
    ("profil", _("Profil"), "bi-person-circle", "profil", None, _("Compte")),
    ("etablissement", _("Établissement"), "bi-building", "etablissements", None, _("Compte")),
]

PRIORITES_PAR_ROLE = {
    "Administrateur de l'établissement": ["accueil", "apprenants", "academique", "personnel"],
    "Enseignant": ["accueil", "classes", "notes", "resultats"],
    "Secrétaire": ["accueil", "apprenants", "inscriptions", "structure"],
    "Directeur": ["accueil", "personnel", "academique", "rapports"],
    "Responsable pédagogique": ["accueil", "academique", "pedagogie", "resultats"],
    "Parent": ["accueil", "portail", "profil", "etablissement"],
    "Apprenant": ["accueil", "portail", "profil", "etablissement"],
    "Comptable": ["accueil", "paiements", "factures", "depenses"],
}


ALIAS_ACTIFS = {
    "academique": ("academique:annee_creer", "academique:periodes"),
    "apprenants": ("apprenants:creer", "apprenants:detail"),
    "importations": ("importations:detail",),
    "inscriptions": ("apprenants:inscription_creer", "apprenants:inscription_detail"),
    "admissions": ("admissions:detail",),
    "notes": ("evaluations:configuration", "evaluations:saisie"),
    "resultats": ("evaluations:synthese",),
    "pedagogie": ("pedagogie:niveau",),
    "ressources": ("pedagogie:telecharger_ressource", "pedagogie:quiz_detail"),
    "personnel": ("personnel_creer",),
    "presence_appel": ("presences:appel",),
    "presence_historique": ("presences:appel",),
    "presence_portail": ("presences:mes_absences",),
    "cahier": ("cahier:mon_cahier",),
    "cahier_gerer": ("cahier:entrees", "cahier:entree_creer"),
    "devoirs_gerer": ("cahier:devoirs", "cahier:devoir_creer"),
    "messages": ("messagerie:nouveau", "messagerie:conversation", "messagerie:notifications"),
    "emploi": ("emploi_du_temps:gestion", "emploi_du_temps:creneau_creer", "emploi_du_temps:salles"),
    "emploi_portail": ("emploi_du_temps:mon_emploi",),
}


def _autorise(request, permissions):
    if permissions is None:
        return True
    if "plateforme.administrer" in permissions:
        return request.user.is_superuser
    return any(verifier_permission(request.user, request.appartenance, code) for code in permissions)


def construire_navigation(request):
    """Renvoie les 4 liens du bas (mobile), les groupes du panneau « Plus » et la sidebar (bureau)."""
    libelles = profil_etablissement(getattr(request.etablissement, "type", None))["libelles"]
    cles_libelles = {
        "classes": "groupes",
        "resultats": "evaluations",
        "portail": "evaluations",
        "apprenants": "apprenants",
        "pedagogie": "cours",
    }
    accessibles = [
        {"cle": c, "libelle": libelles.get(cles_libelles.get(c), l), "icone": i,
         "url": reverse(u), "route": u, "categorie": cat}
        for c, l, i, u, p, cat in ENTREES
        if _autorise(request, p)
    ]
    if "cahier" in {entree["cle"] for entree in accessibles} and "cahier_gerer" in {
        entree["cle"] for entree in accessibles
    }:
        accessibles = [entree for entree in accessibles if entree["cle"] != "cahier"]
    if any(e["cle"] == "resultats" for e in accessibles):  # évite le doublon « Résultats »
        accessibles = [e for e in accessibles if e["cle"] != "portail"]
    par_cle = {e["cle"]: e for e in accessibles}
    role = request.appartenance.role.nom if request.appartenance else None
    ordre = PRIORITES_PAR_ROLE.get(role, ["accueil", "apprenants", "academique", "resultats"])
    principales = [par_cle[c] for c in ordre if c in par_cle]
    for entree in accessibles:  # complète jusqu'à 4 liens si le rôle en a moins
        if len(principales) >= 4:
            break
        if entree not in principales:
            principales.append(entree)
    principales = principales[:4]
    groupes = {}
    for entree in accessibles:
        if entree not in principales:
            groupes.setdefault(entree["categorie"], []).append(entree)
    sidebar = {}
    for entree in accessibles:
        sidebar.setdefault(entree["categorie"], []).append(entree)
    courante = request.resolver_match.view_name if request.resolver_match else ""
    for entree in accessibles:
        entree["active"] = courante == entree["route"] or courante in ALIAS_ACTIFS.get(entree["cle"], ())
    return {"principales": principales, "groupes_plus": groupes, "sidebar": sidebar}
