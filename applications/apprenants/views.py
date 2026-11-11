from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from applications.academique.models import AnneeAcademique
from applications.academique.services import annee_active
from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier

from . import services
from .forms import (
    FormulaireApprenant, FormulaireChangementClasse, FormulaireDecision, FormulaireFinAnnee,
    FormulaireIncidentDisciplinaire, FormulaireInscription, FormulairePiece,
)
from .models import Apprenant, IncidentDisciplinaire, Inscription

PAR_PAGE = 20


@permission_requise("apprenants.consulter", "apprenants.gerer")
def liste(request):
    terme = request.GET.get("q", "").strip()
    requete = Apprenant.objects.all()
    if terme:
        requete = requete.filter(Q(nom__icontains=terme) | Q(prenoms__icontains=terme) | Q(matricule__icontains=terme))
    page = Paginator(requete, PAR_PAGE).get_page(request.GET.get("page"))
    return render(request, "apprenants/liste.html", {"page": page, "q": terme, "parametres": f"q={terme}&" if terme else ""})


@permission_requise("apprenants.gerer")
def creer(request):
    formulaire = FormulaireApprenant(
        request.POST or None, request.FILES or None, etablissement=request.etablissement
    )
    if request.method == "POST" and formulaire.is_valid():
        d = formulaire.cleaned_data
        try:
            with transaction.atomic():
                responsable = None
                if d.get("responsable_nom"):
                    responsable = services.creer_responsable(
                        request.etablissement, d["responsable_nom"], d.get("responsable_prenoms", ""),
                        d.get("responsable_telephone", ""), d.get("responsable_email", ""),
                    )
                apprenant = services.creer_apprenant(
                    request.etablissement, d["nom"], d["prenoms"], d["sexe"], d["date_naissance"],
                    responsable=responsable, lien=d.get("responsable_lien") or "TUTEUR",
                    par=request.user, lieu_naissance=d["lieu_naissance"], email=d["email"],
                    telephone=d["telephone"], adresse=d["adresse"], photo=d["photo"] or "",
                )
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
        else:
            messages.success(request, f"Dossier créé. Matricule : {apprenant.matricule}.")
            if a_la_permission(request, "inscriptions.enregistrer"):
                return redirect(f"/apprenants/inscriptions/nouvelle/?apprenant={apprenant.pk}")
            return redirect("apprenants:detail", pk=apprenant.pk)
    return render(request, "apprenants/creer.html", {"formulaire": formulaire})


@permission_requise("apprenants.gerer")
def modifier(request, pk):
    apprenant = get_object_or_404(Apprenant, pk=pk)
    if apprenant.anonymise:
        messages.error(request, "Un dossier anonymisé ne peut plus être modifié.")
        return redirect("apprenants:detail", pk=apprenant.pk)

    formulaire = FormulaireApprenant(
        request.POST or None, request.FILES or None,
        etablissement=request.etablissement, instance=apprenant,
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            apprenant = services.modifier_apprenant(
                apprenant, par=request.user, **formulaire.cleaned_data
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Le dossier de l’apprenant a été mis à jour.")
            return redirect("apprenants:detail", pk=apprenant.pk)
    return render(request, "apprenants/creer.html", {
        "formulaire": formulaire, "apprenant": apprenant, "edition": True,
    })


@permission_requise("apprenants.consulter", "apprenants.gerer")
def detail(request, pk):
    apprenant = get_object_or_404(Apprenant, pk=pk)
    return render(request, "apprenants/detail.html", {
        "apprenant": apprenant,
        "inscriptions": apprenant.inscriptions.select_related("annee", "niveau", "classe", "programme"),
        "liens": apprenant.liens_responsables.select_related("responsable"),
    })


@permission_requise("apprenants.consulter", "apprenants.gerer", "inscriptions.enregistrer", "inscriptions.decider")
def inscriptions(request):
    annee_id = request.GET.get("annee")
    annee = AnneeAcademique.objects.filter(pk=annee_id).first() if annee_id else annee_active(request.etablissement)
    statut = request.GET.get("statut", "")
    terme = request.GET.get("q", "").strip()
    uniquement_a_valider = request.GET.get("a_valider") == "1"
    requete = Inscription.objects.select_related("apprenant", "annee", "niveau", "classe", "programme")
    if annee:
        requete = requete.filter(annee=annee)
    if statut:
        requete = requete.filter(statut=statut)
    if uniquement_a_valider:
        requete = requete.filter(statut__in=(
            Inscription.Statut.EN_ATTENTE, Inscription.Statut.CORRECTION_DEMANDEE,
        ))
    if terme:
        requete = requete.filter(Q(apprenant__nom__icontains=terme) | Q(apprenant__prenoms__icontains=terme)
                                 | Q(apprenant__matricule__icontains=terme))
    page = Paginator(requete, PAR_PAGE).get_page(request.GET.get("page"))
    parametres = f"annee={annee.pk if annee else ''}&statut={statut}&q={terme}&a_valider={'1' if uniquement_a_valider else ''}&"
    return render(request, "apprenants/inscriptions.html", {
        "page": page, "annee": annee, "annees": AnneeAcademique.objects.all(), "statut": statut, "q": terme,
        "statuts": Inscription.Statut.choices, "parametres": parametres,
        "uniquement_a_valider": uniquement_a_valider,
        "peut_decider": a_la_permission(request, "inscriptions.decider"),
    })


@permission_requise("inscriptions.decider")
@require_POST
def inscriptions_valider_lot(request):
    destination = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        destination = reverse("apprenants:inscriptions")

    identifiants = {
        int(valeur) for valeur in request.POST.getlist("inscriptions")
        if valeur.isdecimal() and int(valeur) > 0
    }
    if not identifiants:
        messages.warning(request, "Sélectionnez au moins une inscription à valider.")
        return redirect(destination)

    inscriptions_selectionnees = list(
        Inscription.objects.filter(
            pk__in=identifiants,
            statut__in=(
                Inscription.Statut.EN_ATTENTE, Inscription.Statut.CORRECTION_DEMANDEE,
            ),
        ).order_by("pk")
    )
    if not inscriptions_selectionnees:
        messages.warning(request, "Aucune inscription sélectionnée ne peut être validée.")
        return redirect(destination)

    try:
        with transaction.atomic():
            for inscription in inscriptions_selectionnees:
                services.decider_inscription(
                    inscription, "VALIDER", request.user
                )
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(
            request, f"{len(inscriptions_selectionnees)} inscription(s) validée(s)."
        )
    return redirect(destination)


@permission_requise("inscriptions.enregistrer")
def inscription_creer(request):
    initial = {"apprenant": request.GET.get("apprenant")} if request.GET.get("apprenant") else None
    formulaire = FormulaireInscription(request.POST or None, initial=initial, etablissement=request.etablissement)
    annee = annee_active(request.etablissement)
    if annee is None:
        messages.warning(request, "Aucune année académique active : activez-en une avant d'inscrire des apprenants.")
    if request.method == "POST" and formulaire.is_valid():
        d = formulaire.cleaned_data
        try:
            inscription = services.creer_inscription(
                request.etablissement, d["apprenant"], d["niveau"], classe=d.get("classe"),
                programme=d.get("programme"), type_inscription=d["type_inscription"], par=request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Demande d'inscription enregistrée (en attente de validation).")
            return redirect("apprenants:inscription_detail", pk=inscription.pk)
    return render(request, "apprenants/inscription_form.html", {"formulaire": formulaire, "annee": annee})


@permission_requise("inscriptions.enregistrer", "inscriptions.decider")
def inscription_modifier(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)
    correction_validee = inscription.statut == Inscription.Statut.VALIDEE
    if correction_validee:
        raison = services.raison_blocage_correction_validee(inscription)
        if raison:
            messages.error(request, raison)
            return redirect("apprenants:inscription_detail", pk=inscription.pk)
    elif inscription.statut not in (
        Inscription.Statut.EN_ATTENTE, Inscription.Statut.CORRECTION_DEMANDEE,
    ):
        messages.error(
            request,
            "Seules les inscriptions en attente ou en correction peuvent être modifiées. "
            "Pour une inscription validée, utilisez le changement de classe.",
        )
        return redirect("apprenants:inscription_detail", pk=inscription.pk)

    formulaire = FormulaireInscription(
        request.POST or None, etablissement=request.etablissement, inscription=inscription,
        correction_validee=correction_validee,
    )
    if request.method == "POST" and formulaire.is_valid():
        d = formulaire.cleaned_data
        try:
            inscription = services.modifier_inscription(
                inscription, d["apprenant"], d["niveau"], classe=d.get("classe"),
                programme=d.get("programme"), type_inscription=d["type_inscription"], par=request.user,
                motif_correction=d.get("motif_correction", ""),
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            if correction_validee:
                messages.success(request, "La correction du niveau a été enregistrée et auditée.")
            else:
                messages.success(request, "La demande d’inscription a été mise à jour.")
            return redirect("apprenants:inscription_detail", pk=inscription.pk)
    return render(request, "apprenants/inscription_form.html", {
        "formulaire": formulaire, "annee": inscription.annee,
        "inscription": inscription, "edition": True, "correction_validee": correction_validee,
    })


@permission_requise("apprenants.consulter", "apprenants.gerer", "inscriptions.enregistrer", "inscriptions.decider")
def inscription_detail(request, pk):
    inscription = get_object_or_404(
        Inscription.objects.select_related("apprenant", "annee", "niveau", "classe", "programme__faculte"), pk=pk
    )
    peut_decider = a_la_permission(request, "inscriptions.decider")
    peut_enregistrer = a_la_permission(request, "inscriptions.enregistrer")
    raison_correction = (
        services.raison_blocage_correction_validee(inscription)
        if inscription.statut == Inscription.Statut.VALIDEE else ""
    )
    contexte = {
        "inscription": inscription, "decisions": inscription.decisions.select_related("auteur"),
        "pieces": inscription.pieces.all(), "peut_decider": peut_decider,
        "formulaire_piece": FormulairePiece(),
        "peut_modifier": (
            (peut_enregistrer or peut_decider)
            and (
                inscription.statut in (
                    Inscription.Statut.EN_ATTENTE, Inscription.Statut.CORRECTION_DEMANDEE,
                )
                or (inscription.statut == Inscription.Statut.VALIDEE and not raison_correction)
            )
        ),
        "raison_correction": raison_correction,
    }
    if peut_decider:
        contexte["formulaire_decision"] = FormulaireDecision()
        contexte["formulaire_fin_annee"] = FormulaireFinAnnee(initial={"decision": inscription.decision_fin_annee or None})
        contexte["formulaire_classe"] = FormulaireChangementClasse(inscription=inscription)
    if a_la_permission(request, "apprenants.gerer"):
        contexte["formulaire_incident"] = FormulaireIncidentDisciplinaire()
        contexte["incidents"] = IncidentDisciplinaire.objects.filter(inscription=inscription)
    return render(request, "apprenants/inscription_detail.html", contexte)


@permission_requise("inscriptions.enregistrer", "inscriptions.decider")
@require_POST
def inscription_action(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)
    action = request.POST.get("action")
    try:
        if action == "piece":
            formulaire = FormulairePiece(request.POST, request.FILES)
            if formulaire.is_valid():
                piece = formulaire.save(commit=False)
                piece.inscription, piece.etablissement = inscription, inscription.etablissement
                piece.save()
                messages.success(request, "Pièce ajoutée.")
            else:
                messages.error(request, "Pièce invalide : libellé et fichier sont obligatoires.")
        elif not a_la_permission(request, "inscriptions.decider"):
            messages.error(request, "Vous n'avez pas l'autorisation d'effectuer cette action.")
        elif action == "decider":
            formulaire = FormulaireDecision(request.POST)
            if formulaire.is_valid():
                services.decider_inscription(
                    inscription, formulaire.cleaned_data["decision"], request.user, formulaire.cleaned_data["motif"]
                )
                messages.success(request, "Décision enregistrée.")
        elif action == "fin_annee":
            formulaire = FormulaireFinAnnee(request.POST)
            if formulaire.is_valid():
                services.definir_decision_fin_annee(inscription, formulaire.cleaned_data["decision"], request.user)
                messages.success(request, "Décision de fin d'année enregistrée.")
        elif action == "classe":
            formulaire = FormulaireChangementClasse(request.POST, inscription=inscription)
            if formulaire.is_valid():
                services.changer_classe(inscription, formulaire.cleaned_data["classe"], request.user)
                messages.success(request, "Classe modifiée.")
        elif action == "reinscrire":
            nouvelle = services.reinscrire(inscription, par=request.user)
            messages.success(request, "Réinscription préparée pour la nouvelle année.")
            return redirect("apprenants:inscription_detail", pk=nouvelle.pk)
        elif action == "incident" and a_la_permission(request, "apprenants.gerer"):
            formulaire = FormulaireIncidentDisciplinaire(request.POST)
            if not formulaire.is_valid():
                messages.error(request, "Vérifiez les informations de l'incident disciplinaire.")
            else:
                services.enregistrer_incident(
                    inscription, **formulaire.cleaned_data, par=request.user
                )
                messages.success(request, "Incident disciplinaire enregistré.")
        else:
            messages.error(request, "Action inconnue.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("apprenants:inscription_detail", pk=inscription.pk)
