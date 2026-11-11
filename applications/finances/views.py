from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Sum
from django.views.decorators.http import require_POST

from applications.apprenants.models import Apprenant, LienResponsable
from applications.noyau.decorateurs import a_la_permission
from applications.noyau.decorateurs import permission_requise
from applications.noyau.exceptions import ErreurMetier

from . import services
from .forms import (
    FormulaireAnnulation, FormulaireDepense, FormulaireEncaissement, FormulaireGrilleFrais,
    FormulairePaiement, FormulairePeriodeRapport, FormulaireRemboursement, FormulaireTypeFrais,
)
from .models import Depense, Facture, GrilleFrais, Paiement, TypeFrais


@permission_requise("finances.consulter")
def paiements(request):
    page = Paginator(
        Paiement.objects.select_related("apprenant", "enregistre_par").order_by("-date_paiement", "-id"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "finances/paiements.html", {
        "page": page, "peut_gerer": a_la_permission(request, "finances.gerer"),
    })


@permission_requise("finances.gerer")
def paiement_creer(request):
    formulaire = FormulairePaiement(
        request.POST or None, etablissement=request.etablissement
    )
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            services.enregistrer_paiement(
                request.etablissement, donnees["apprenant"], donnees["montant"],
                donnees["date_paiement"], donnees["motif"], donnees["mode"], request.user,
                donnees["reference"],
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Paiement enregistré.")
            return redirect("finances:paiements")
    return render(request, "finances/paiement_creer.html", {"formulaire": formulaire})


@permission_requise("finances.consulter")
def depenses(request):
    page = Paginator(
        Depense.objects.select_related("enregistree_par").order_by("-date_depense", "-id"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "finances/depenses.html", {"page": page})


@permission_requise("finances.gerer")
def depense_creer(request):
    formulaire = FormulaireDepense(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            services.enregistrer_depense(
                request.etablissement, donnees["montant"], donnees["date_depense"],
                donnees["categorie"], donnees["motif"], request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Dépense enregistrée.")
            return redirect("finances:depenses")
    return render(request, "finances/depense_creer.html", {"formulaire": formulaire})


@permission_requise("finances.consulter")
def rapports(request):
    formulaire = FormulairePeriodeRapport(request.POST or None)
    rapport = None
    if request.method == "POST" and formulaire.is_valid():
        try:
            rapport = services.rapport_financier(
                request.etablissement, formulaire.cleaned_data["debut"], formulaire.cleaned_data["fin"]
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
    if rapport is None and request.method == "GET":
        aujourd_hui = timezone.localdate()
        rapport = services.rapport_financier(
            request.etablissement, aujourd_hui.replace(day=1), aujourd_hui
        )
    return render(request, "finances/rapports.html", {
        "rapport": rapport, "formulaire": formulaire,
        "synthese": services.synthese_financiere(request.etablissement),
    })


@permission_requise("finances.consulter")
def factures(request):
    page = Paginator(
        Facture.objects.select_related("inscription__apprenant", "inscription__annee").order_by("-date_emission", "-pk"),
        25,
    ).get_page(request.GET.get("page"))
    return render(request, "finances/factures.html", {"page": page})


@permission_requise("finances.consulter", "finances.consulter_propres")
def facture_detail(request, pk):
    factures_autorisees = (
        Facture.objects.select_related("inscription__apprenant", "inscription__annee")
        if a_la_permission(request, "finances.consulter")
        else services.factures_accessibles(request.user, request.etablissement)
    )
    facture = get_object_or_404(factures_autorisees, pk=pk)
    return render(request, "finances/facture.html", {
        "facture": facture, "lignes": facture.lignes.all(),
        "repartition": services.repartition_echeances(facture),
        "paye": services.total_paye(facture), "solde": services.solde_facture(facture),
        "paiements": facture.paiements.select_related("recu_par"),
        "formulaire_encaissement": FormulaireEncaissement(initial={"montant": services.solde_facture(facture)}),
        "formulaire_annulation": FormulaireAnnulation(),
        "peut_gerer": a_la_permission(request, "finances.gerer"),
    })


@permission_requise("finances.gerer")
@require_POST
def facture_encaisser(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    formulaire = FormulaireEncaissement(request.POST)
    if not formulaire.is_valid():
        messages.error(request, "Le montant, le mode de paiement ou la référence est invalide.")
        return redirect("finances:facture_detail", pk=pk)
    try:
        paiement = services.encaisser_facture(
            facture, formulaire.cleaned_data["montant"], formulaire.cleaned_data["mode"],
            formulaire.cleaned_data["reference"], request.user,
        )
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, f"Paiement enregistré. Reçu {paiement.numero_recu}.")
    return redirect("finances:facture_detail", pk=pk)


@permission_requise("finances.gerer")
@require_POST
def facture_annuler(request, pk):
    facture = get_object_or_404(Facture, pk=pk)
    formulaire = FormulaireAnnulation(request.POST)
    if not formulaire.is_valid():
        messages.error(request, "Un motif d'annulation est obligatoire.")
        return redirect("finances:facture_detail", pk=pk)
    try:
        services.annuler_facture(facture, formulaire.cleaned_data["motif"], request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Facture annulée.")
    return redirect("finances:facture_detail", pk=pk)


@permission_requise("finances.gerer")
def paiement_rembourser(request, pk):
    paiement = get_object_or_404(
        Paiement.objects.select_related("facture", "apprenant"), pk=pk
    )
    rembourse = paiement.remboursements.aggregate(total=Sum("montant"))["total"] or 0
    restant = paiement.montant - rembourse
    formulaire = FormulaireRemboursement(
        request.POST or None, initial={"montant": restant} if request.method == "GET" else None
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.enregistrer_remboursement(
                paiement, formulaire.cleaned_data["montant"], formulaire.cleaned_data["motif"], request.user
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Remboursement enregistré et journalisé.")
            if paiement.facture_id:
                return redirect("finances:facture_detail", pk=paiement.facture_id)
            return redirect("finances:paiements")
    return render(request, "finances/remboursement.html", {
        "paiement": paiement, "restant": restant, "formulaire": formulaire,
        "remboursements": paiement.remboursements.all(),
    })


@permission_requise("finances.gerer")
def tarifs(request):
    form_type = FormulaireTypeFrais(request.POST if request.POST.get("cible") == "type" else None)
    form_grille = FormulaireGrilleFrais(
        request.POST if request.POST.get("cible") == "grille" else None,
        etablissement=request.etablissement,
    )
    if request.method == "POST" and request.POST.get("cible") == "type" and form_type.is_valid():
        try:
            services.creer_type_frais(request.etablissement, form_type.cleaned_data["nom"], request.user)
        except ErreurMetier as erreur:
            form_type.add_error("nom", str(erreur))
        else:
            messages.success(request, "Type de frais créé.")
            return redirect("finances:tarifs")
    if request.method == "POST" and request.POST.get("cible") == "grille" and form_grille.is_valid():
        donnees = form_grille.cleaned_data
        try:
            services.creer_grille_frais(
                request.etablissement, donnees["annee"], donnees["niveau"], donnees["type_frais"],
                donnees["montant"], donnees["nombre_echeances"], donnees["premiere_echeance"], request.user,
            )
        except ErreurMetier as erreur:
            form_grille.add_error(None, str(erreur))
        else:
            messages.success(request, "Grille de frais enregistrée.")
            return redirect("finances:tarifs")
    return render(request, "finances/tarifs.html", {
        "form_type": form_type, "form_grille": form_grille,
        "types": TypeFrais.objects.all(),
        "grilles": GrilleFrais.objects.select_related("annee", "niveau", "type_frais"),
    })


@permission_requise("finances.consulter_propres")
def mes_factures(request):
    factures_utilisateur = services.factures_accessibles(request.user, request.etablissement)
    return render(request, "finances/mes_factures.html", {
        "factures": [{
            "facture": facture, "solde": services.solde_facture(facture),
            "exigible": services.montant_exigible(facture),
        } for facture in factures_utilisateur],
    })


@permission_requise("finances.consulter", "finances.consulter_propres")
def recu(request, pk):
    paiement = get_object_or_404(
        Paiement.objects.select_related("apprenant", "facture", "recu_par"), pk=pk
    )
    if not a_la_permission(request, "finances.consulter"):
        autorise = Apprenant.sans_filtre.filter(
            etablissement=request.etablissement, utilisateur=request.user, paiements=paiement
        ).exists() or LienResponsable.objects.filter(
            responsable__utilisateur=request.user, apprenant__paiements=paiement
        ).exists()
        if not autorise:
            raise PermissionDenied
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    flux = BytesIO()
    document = SimpleDocTemplate(flux, pagesize=A5, title=f"Reçu {paiement.numero_recu or paiement.pk}")
    style = getSampleStyleSheet()
    lignes = [
        ["Reçu n°", paiement.numero_recu or f"Paiement {paiement.pk}"],
        ["Date", timezone.localtime(paiement.cree_le).strftime("%d/%m/%Y %H:%M")],
        ["Apprenant", str(paiement.apprenant)],
        ["Motif", paiement.motif],
        ["Mode", paiement.get_mode_display()],
        ["Référence", paiement.reference or "—"],
        ["Montant payé", f"{paiement.montant:.2f} {request.etablissement.devise}"],
    ]
    if paiement.facture_id:
        lignes.extend([
            ["Facture", paiement.facture.numero],
            ["Solde restant", f"{services.solde_facture(paiement.facture):.2f} {paiement.facture.devise}"],
        ])
    tableau = Table(lignes, colWidths=[110, 220])
    tableau.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E3F1F2")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    document.build([
        Paragraph(request.etablissement.nom, style["Title"]),
        Paragraph("Reçu de paiement", style["Heading3"]), Spacer(1, 8), tableau,
    ])
    reponse = HttpResponse(flux.getvalue(), content_type="application/pdf")
    reponse["Content-Disposition"] = f'inline; filename="{paiement.numero_recu or paiement.pk}.pdf"'
    return reponse
