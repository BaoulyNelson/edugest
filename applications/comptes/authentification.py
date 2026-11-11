"""Backend d'authentification par adresse e-mail avec limitation des essais."""
import hashlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.utils import timezone

from .models import TentativeConnexion

MAX_TENTATIVES = 5
DUREE_BLOCAGE = timedelta(minutes=15)
DUREE_FENETRE = timedelta(minutes=15)


def _cle_tentatives(request, identifiant):
    adresse_ip = request.META.get("REMOTE_ADDR", "") if request is not None else ""
    valeur = f"{identifiant.casefold().strip()}|{adresse_ip}"
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()


def _tentatives_bloquees(cle):
    tentative = TentativeConnexion.objects.filter(cle=cle).first()
    return tentative is not None and tentative.est_bloquee


@transaction.atomic
def _enregistrer_echec(cle):
    tentative, _ = TentativeConnexion.objects.select_for_update().get_or_create(cle=cle)
    maintenant = timezone.now()
    if maintenant - tentative.derniere_tentative > DUREE_FENETRE:
        tentative.nombre = 0
        tentative.bloquee_jusqua = None
    tentative.nombre += 1
    tentative.derniere_tentative = maintenant
    if tentative.nombre >= MAX_TENTATIVES:
        tentative.bloquee_jusqua = maintenant + DUREE_BLOCAGE
    tentative.save(update_fields=("nombre", "derniere_tentative", "bloquee_jusqua"))


def _effacer_tentatives(cle):
    TentativeConnexion.objects.filter(cle=cle).delete()


class BackendEmail(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        modele = get_user_model()
        identifiant = (username or kwargs.get("email") or "").strip()
        if not identifiant or password is None:
            return None

        cle = _cle_tentatives(request, identifiant)
        if _tentatives_bloquees(cle):
            return None

        utilisateur = modele.objects.filter(email__iexact=identifiant).first() or \
            modele.objects.filter(username__iexact=identifiant).first()
        if utilisateur is None:
            modele().set_password(password)
            _enregistrer_echec(cle)
            return None
        if utilisateur.check_password(password) and self.user_can_authenticate(utilisateur):
            _effacer_tentatives(cle)
            return utilisateur
        _enregistrer_echec(cle)
        return None
