from .navigation import construire_navigation
from .terminologie import profil_etablissement


def _url_logo_existant(logo):
    if logo and logo.name and logo.storage.exists(logo.name):
        return logo.url
    return None


def contexte_interface(request):
    """Variables communes à tous les gabarits : navigation, établissement, notifications."""
    utilisateur = getattr(request, "user", None)
    etablissement = getattr(request, "etablissement", None)
    from applications.noyau.models import ConfigurationPlateforme

    marque_plateforme = ConfigurationPlateforme.objects.filter(pk=1).first()
    if marque_plateforme is None:
        marque_plateforme = ConfigurationPlateforme(nom="EduGest", nom_court="EduGest")
    favicon_url = _url_logo_existant(getattr(etablissement, "logo", None))
    if favicon_url is None:
        favicon_url = _url_logo_existant(marque_plateforme.logo)

    contexte = {
        "navigation": None,
        "etablissement_courant": etablissement,
        "etablissements_disponibles": [],
        "annee_academique_active": None,
        "marque_plateforme": marque_plateforme,
        "favicon_url": favicon_url,
        **profil_etablissement(getattr(etablissement, "type", None)),
    }
    if utilisateur is None or not utilisateur.is_authenticated or etablissement is None:
        return contexte
    from applications.noyau.models import Appartenance, Etablissement

    etablissements = Etablissement.objects.filter(
        pk__in=Appartenance.sans_filtre.filter(
            utilisateur=utilisateur, actif=True, etablissement__actif=True
        ).values("etablissement_id")
    )
    contexte["etablissements_disponibles"] = list(etablissements.order_by("nom"))
    from applications.academique.services import annee_active

    contexte["annee_academique_active"] = annee_active(etablissement)
    contexte["navigation"] = construire_navigation(request)
    from applications.noyau.services import verifier_permission

    notifications = []
    if verifier_permission(utilisateur, request.appartenance, "inscriptions.decider"):
        from applications.apprenants.models import Inscription

        en_attente = Inscription.objects.filter(statut="EN_ATTENTE").count()
        if en_attente:
            notifications.append(
                {"texte": f"{en_attente} inscription(s) en attente de décision", "route": "apprenants:inscriptions",
                 "parametres": "?statut=EN_ATTENTE"}
            )
    from applications.presences.models import NotificationPresence

    notifications.extend(
        {
            "texte": notification.titre,
            "route": "presences:mes_absences",
            "parametres": "",
        }
        for notification in NotificationPresence.objects.filter(
            etablissement=etablissement, destinataire=utilisateur, lue=False,
        )[:10]
    )
    from applications.cahier.models import NotificationCahier

    notifications.extend(
        {"texte": notification.titre, "url": notification.url}
        for notification in NotificationCahier.objects.filter(
            etablissement=etablissement, destinataire=utilisateur, lue=False,
        )[:max(0, 10 - len(notifications))]
    )
    from applications.messagerie.models import NotificationMessage

    notifications.extend(
        {"texte": notification.titre, "url": notification.url}
        for notification in NotificationMessage.objects.filter(
            etablissement=etablissement, destinataire=utilisateur, lue=False,
        )[:max(0, 10 - len(notifications))]
    )
    contexte["notifications"] = notifications
    return contexte
