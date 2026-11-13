from django.core.exceptions import ValidationError
from django.db import transaction

from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit

from .models import Evenement, Publication


def _sauvegarder(objet):
    try:
        objet.save()
    except ValidationError as erreur:
        raise ErreurMetier("; ".join(erreur.messages)) from erreur
    return objet


@transaction.atomic
def creer_publication(etablissement, auteur, **donnees):
    publication = _sauvegarder(Publication(etablissement=etablissement, auteur=auteur, **donnees))
    enregistrer_audit(
        etablissement, auteur, "actualites.publication.creation", publication,
        apres={"titre": publication.titre, "type": publication.type, "statut": publication.statut},
    )
    return publication


@transaction.atomic
def modifier_publication(publication, auteur, **donnees):
    publication = Publication.sans_filtre.select_for_update().get(pk=publication.pk)
    avant = {"titre": publication.titre, "type": publication.type, "statut": publication.statut}
    for champ, valeur in donnees.items():
        setattr(publication, champ, valeur)
    _sauvegarder(publication)
    enregistrer_audit(
        publication.etablissement, auteur, "actualites.publication.modification", publication,
        avant=avant, apres={"titre": publication.titre, "type": publication.type, "statut": publication.statut},
    )
    return publication


@transaction.atomic
def archiver_publication(publication, auteur):
    publication = Publication.sans_filtre.select_for_update().get(pk=publication.pk)
    if publication.statut == Publication.Statut.ARCHIVEE:
        raise ErreurMetier("Cette publication est déjà archivée.")
    ancien_statut = publication.statut
    publication.statut = Publication.Statut.ARCHIVEE
    publication.save(update_fields=["statut", "modifie_le"])
    enregistrer_audit(
        publication.etablissement, auteur, "actualites.publication.archivage", publication,
        avant={"statut": ancien_statut}, apres={"statut": publication.statut},
    )
    return publication


@transaction.atomic
def creer_evenement(etablissement, auteur, **donnees):
    evenement = _sauvegarder(Evenement(etablissement=etablissement, auteur=auteur, **donnees))
    enregistrer_audit(
        etablissement, auteur, "actualites.evenement.creation", evenement,
        apres={"titre": evenement.titre, "debut": evenement.debut.isoformat()},
    )
    return evenement


@transaction.atomic
def modifier_evenement(evenement, auteur, **donnees):
    evenement = Evenement.sans_filtre.select_for_update().get(pk=evenement.pk)
    avant = {"titre": evenement.titre, "debut": evenement.debut.isoformat(), "statut": evenement.statut}
    for champ, valeur in donnees.items():
        setattr(evenement, champ, valeur)
    _sauvegarder(evenement)
    enregistrer_audit(
        evenement.etablissement, auteur, "actualites.evenement.modification", evenement,
        avant=avant,
        apres={"titre": evenement.titre, "debut": evenement.debut.isoformat(), "statut": evenement.statut},
    )
    return evenement
