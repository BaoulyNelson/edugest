import os
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.presences.services import inscrits

from . import services
from .forms import (
    FormulaireAppreciation, FormulaireCorrection, FormulaireDevoir, FormulaireEntree, FormulaireRemise,
)
from .models import (
    Devoir, EntreeCahier, NotificationCahier, PieceJointeDevoir, PieceJointeRemise, Remise,
)


def _tout(request):
    return a_la_permission(request, "cahier.gerer_tous")


def _peut_gerer(request):
    return a_la_permission(request, "cahier.gerer") or _tout(request)


@permission_requise("cahier.gerer", "cahier.gerer_tous")
def entrees(request):
    liste = EntreeCahier.objects.select_related(
        "classe__niveau", "matiere_niveau__matiere", "enseignant__utilisateur",
    )
    if not _tout(request):
        liste = liste.filter(enseignant=request.appartenance)
    return render(request, "cahier/entrees.html", {"entrees": liste[:60]})


@permission_requise("cahier.gerer", "cahier.gerer_tous")
def entree_creer(request):
    formulaire = FormulaireEntree(
        request.POST or None,
        request.FILES or None,
        paires=services.paires_accessibles(request.etablissement, request.appartenance, _tout(request)),
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.creer_entree(
                request.etablissement,
                request.appartenance,
                formulaire.cleaned_data,
                tout=_tout(request),
                acteur=request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Séance ajoutée au cahier de textes.")
            return redirect("cahier:entrees")
    return render(request, "cahier/entree_form.html", {"formulaire": formulaire})


@permission_requise("cahier.gerer", "cahier.gerer_tous")
def devoirs(request):
    liste = Devoir.objects.select_related(
        "classe__niveau", "matiere_niveau__matiere", "enseignant__utilisateur",
    )
    if not _tout(request):
        liste = liste.filter(enseignant=request.appartenance)
    return render(request, "cahier/devoirs.html", {"devoirs": liste[:60]})


@permission_requise("cahier.gerer", "cahier.gerer_tous")
def devoir_creer(request):
    formulaire = FormulaireDevoir(
        request.POST or None,
        request.FILES or None,
        paires=services.paires_accessibles(request.etablissement, request.appartenance, _tout(request)),
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            devoir = services.publier_devoir(
                request.etablissement,
                request.appartenance,
                formulaire.cleaned_data,
                tout=_tout(request),
                acteur=request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Devoir publié ; les élèves et responsables de la classe ont été prévenus.")
            return redirect("cahier:devoir", pk=devoir.pk)
    return render(request, "cahier/devoir_form.html", {"formulaire": formulaire})


@permission_requise("cahier.gerer", "cahier.gerer_tous", "cahier.consulter", "devoirs.remettre")
def devoir_detail(request, pk):
    devoir = get_object_or_404(
        Devoir.objects.select_related("classe", "matiere_niveau__matiere", "enseignant"),
        pk=pk,
    )
    peut_gerer = _peut_gerer(request)
    contexte = {"devoir": devoir, "maintenant": timezone.now()}
    if peut_gerer:
        if not (_tout(request) or devoir.enseignant_id == getattr(request.appartenance, "pk", None)):
            raise PermissionDenied
        remises = {
            remise.inscription_id: remise
            for remise in devoir.remises.select_related("inscription__apprenant").prefetch_related("pieces_jointes")
        }
        maintenant = timezone.now()
        contexte.update({
            "lignes": [
                {
                    "inscription": inscription,
                    "remise": remises.get(inscription.pk),
                    "statut": (
                        remises[inscription.pk].statut
                        if inscription.pk in remises
                        else "EN_RETARD" if maintenant > devoir.echeance else "A_FAIRE"
                    ),
                }
                for inscription in inscrits(devoir.classe)
            ],
        })
    else:
        inscription = services.inscriptions_de_l_utilisateur(
            request.user, request.etablissement,
        ).filter(classe_id=devoir.classe_id).first()
        if inscription is None:
            raise PermissionDenied
        remise = Remise.objects.filter(
            devoir=devoir, inscription=inscription,
        ).prefetch_related("pieces_jointes").first()
        apres_echeance = timezone.now() > devoir.echeance
        contexte.update({
            "inscription": inscription,
            "remise": remise,
            "peut_deposer": (
                a_la_permission(request, "devoirs.remettre")
                and inscription.apprenant.utilisateur_id == request.user.pk
                and devoir.remise_numerique
                and (
                    not apres_echeance
                    or (remise is not None and devoir.modifier_apres_echeance)
                    or (remise is None and devoir.accepter_remises_tardives)
                )
            ),
            "apres_echeance": apres_echeance,
        })
        if contexte["peut_deposer"]:
            formulaire = FormulaireRemise(request.POST or None, request.FILES or None)
            if request.method == "POST" and formulaire.is_valid():
                try:
                    services.deposer_travail(
                        devoir,
                        inscription,
                        formulaire.cleaned_data["fichier"],
                        formulaire.cleaned_data["commentaire"],
                    )
                except ErreurMetier as erreur:
                    formulaire.add_error(None, str(erreur))
                else:
                    messages.success(request, "Travail déposé.")
                    return redirect("cahier:devoir", pk=pk)
            contexte["formulaire"] = formulaire
        elif (
            a_la_permission(request, "devoirs.remettre")
            and inscription.apprenant.utilisateur_id == request.user.pk
            and devoir.remise_numerique
        ):
            contexte["remise_bloquee"] = True
    NotificationCahier.objects.filter(
        etablissement=request.etablissement,
        destinataire=request.user,
        url=f"/cahier/devoirs/{devoir.pk}/",
        lue=False,
    ).update(lue=True)
    return render(
        request,
        "cahier/devoir_detail.html" if peut_gerer else "cahier/devoir_eleve.html",
        contexte,
    )


@permission_requise("cahier.gerer", "cahier.gerer_tous")
@require_POST
def apprecier(request, pk):
    remise = get_object_or_404(Remise.objects.select_related("devoir", "inscription"), pk=pk)
    if not (_tout(request) or remise.devoir.enseignant_id == request.appartenance.pk):
        raise PermissionDenied
    formulaire = FormulaireAppreciation(request.POST, devoir=remise.devoir)
    if formulaire.is_valid():
        try:
            services.evaluer_remise(
                remise,
                formulaire.cleaned_data["appreciation"],
                request.user,
                formulaire.cleaned_data["note"],
            )
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
            return redirect("cahier:devoir", pk=remise.devoir_id)
        messages.success(request, "Appréciation enregistrée.")
    else:
        erreurs = " ".join(
            erreur for liste in formulaire.errors.values() for erreur in liste
        )
        messages.error(request, f"Appréciation invalide : {erreurs}")
    return redirect("cahier:devoir", pk=remise.devoir_id)


@permission_requise("cahier.gerer", "cahier.gerer_tous")
def remise_correction(request, pk):
    remise = get_object_or_404(
        Remise.objects.select_related(
            "devoir__classe", "devoir__matiere_niveau__matiere", "inscription__apprenant",
        ).prefetch_related("pieces_jointes"),
        pk=pk,
    )
    if not (_tout(request) or remise.devoir.enseignant_id == request.appartenance.pk):
        raise PermissionDenied
    formulaire = FormulaireCorrection(
        request.POST or None,
        devoir=remise.devoir,
        initial={"note": remise.note, "appreciation": remise.appreciation},
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.evaluer_remise(
                remise,
                formulaire.cleaned_data["appreciation"],
                request.user,
                formulaire.cleaned_data["note"],
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Note et rétroaction enregistrées.")
            return redirect("cahier:devoir", pk=remise.devoir_id)
    return render(request, "cahier/remise_correction.html", {
        "devoir": remise.devoir,
        "remise": remise,
        "formulaire": formulaire,
    })


@permission_requise("cahier.consulter")
def mon_cahier(request):
    inscriptions = list(
        services.inscriptions_de_l_utilisateur(request.user, request.etablissement)
        .select_related("annee", "niveau", "classe__niveau", "programme")
        .order_by("apprenant__nom", "apprenant__prenoms")
    )
    classe_ids = {inscription.classe_id for inscription in inscriptions if inscription.classe_id}
    devoirs = Devoir.objects.filter(
        classe_id__in=classe_ids,
    ).select_related(
        "classe__niveau", "matiere_niveau__matiere",
    ).order_by("date_limite", "heure_limite", "pk")
    remises = {
        (remise.devoir_id, remise.inscription_id): remise
        for remise in Remise.objects.filter(
            inscription_id__in=[inscription.pk for inscription in inscriptions],
            devoir__in=devoirs,
        )
    }
    devoirs_eleves = []
    maintenant = timezone.now()
    for inscription in inscriptions:
        if not inscription.classe_id:
            continue
        for devoir in devoirs:
            if devoir.classe_id != inscription.classe_id:
                continue
            remise = remises.get((devoir.pk, inscription.pk))
            devoirs_eleves.append({
                "devoir": devoir,
                "inscription": inscription,
                "remise": remise,
                "statut": (
                    remise.statut
                    if remise
                    else "EN_RETARD" if maintenant > devoir.echeance else "A_FAIRE"
                ),
            })
    entrees = EntreeCahier.objects.filter(
        classe_id__in=classe_ids, date__gte=timezone.localdate() - timedelta(days=45),
    ).select_related("classe", "matiere_niveau__matiere", "enseignant__utilisateur")
    notifications_non_lues = set(NotificationCahier.objects.filter(
        etablissement=request.etablissement, destinataire=request.user, lue=False,
    ).values_list("url", flat=True))
    for ligne in devoirs_eleves:
        ligne["notification_non_lue"] = (
            f"/cahier/devoirs/{ligne['devoir'].pk}/" in notifications_non_lues
        )
    return render(request, "cahier/mon_cahier.html", {
        "inscriptions": inscriptions,
        "devoirs_eleves": devoirs_eleves,
        "entrees": entrees,
        "maintenant": maintenant,
    })


@permission_requise("cahier.gerer", "cahier.gerer_tous", "cahier.consulter", "devoirs.remettre")
def telecharger(request, type_objet, pk):
    famille_inscriptions = services.inscriptions_de_l_utilisateur(request.user, request.etablissement)
    if type_objet == "entree":
        objet = get_object_or_404(EntreeCahier, pk=pk)
        autorise = (
            _tout(request)
            or (
                a_la_permission(request, "cahier.gerer")
                and (
                    objet.enseignant_id == getattr(request.appartenance, "pk", None)
                    or (objet.classe_id, objet.matiere_niveau_id) in services.paires_accessibles(
                        request.etablissement, request.appartenance,
                    )
                )
            )
            or famille_inscriptions.filter(classe_id=objet.classe_id).exists()
        )
    elif type_objet == "devoir":
        objet = get_object_or_404(Devoir, pk=pk)
        autorise = (
            _tout(request)
            or (
                a_la_permission(request, "cahier.gerer")
                and (
                    objet.enseignant_id == getattr(request.appartenance, "pk", None)
                    or (objet.classe_id, objet.matiere_niveau_id) in services.paires_accessibles(
                        request.etablissement, request.appartenance,
                    )
                )
            )
            or famille_inscriptions.filter(classe_id=objet.classe_id).exists()
        )
    elif type_objet == "remise":
        objet = get_object_or_404(
            Remise.objects.select_related("devoir", "inscription__apprenant"), pk=pk,
        )
        autorise = (
            _tout(request)
            or (
                a_la_permission(request, "cahier.gerer")
                and objet.devoir.enseignant_id == getattr(request.appartenance, "pk", None)
            )
            or objet.inscription.apprenant.utilisateur_id == request.user.pk
            or famille_inscriptions.filter(pk=objet.inscription_id).exists()
        )
    elif type_objet == "piece_devoir":
        objet = get_object_or_404(
            PieceJointeDevoir.objects.select_related("devoir"), pk=pk,
        )
        autorise = (
            _tout(request)
            or (
                a_la_permission(request, "cahier.gerer")
                and (
                    objet.devoir.enseignant_id == getattr(request.appartenance, "pk", None)
                    or (objet.devoir.classe_id, objet.devoir.matiere_niveau_id) in services.paires_accessibles(
                        request.etablissement, request.appartenance,
                    )
                )
            )
            or famille_inscriptions.filter(classe_id=objet.devoir.classe_id).exists()
        )
    elif type_objet == "piece_remise":
        objet = get_object_or_404(
            PieceJointeRemise.objects.select_related("remise__devoir", "remise__inscription"),
            pk=pk,
        )
        autorise = (
            _tout(request)
            or (
                a_la_permission(request, "cahier.gerer")
                and objet.remise.devoir.enseignant_id == getattr(request.appartenance, "pk", None)
            )
            or objet.remise.inscription.apprenant.utilisateur_id == request.user.pk
            or famille_inscriptions.filter(pk=objet.remise.inscription_id).exists()
        )
    else:
        raise Http404
    if not autorise:
        raise PermissionDenied
    if not objet.fichier:
        raise Http404
    return FileResponse(
        objet.fichier.open("rb"),
        as_attachment=True,
        filename=os.path.basename(objet.fichier.name),
    )
