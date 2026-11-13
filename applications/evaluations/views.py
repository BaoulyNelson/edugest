from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from applications.academique.models import AnneeAcademique, Classe, Niveau, Periode
from applications.academique.services import annee_active
from applications.apprenants.models import Inscription
from applications.noyau.decorateurs import a_la_permission, permission_requise
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import ParametresEtablissement
from applications.pedagogie.models import AffectationEnseignant, Matiere

from . import services
from .exports import exporter_excel, exporter_pdf
from .forms import FormulaireExamen
from .models import (
    ComposanteEvaluation, ConfigurationEvaluation, DocumentResultat, Examen, Note, ResultatPeriode,
)


def _affectation_autorisee(request, pk):
    """Une affectation n'est accessible qu'à son enseignant (ou à la direction pour la consultation)."""
    affectation = get_object_or_404(
        AffectationEnseignant.objects.select_related("matiere_niveau__matiere", "matiere_niveau__niveau", "classe", "appartenance"),
        pk=pk,
    )
    if affectation.appartenance_id != getattr(request.appartenance, "pk", None):
        raise PermissionDenied("Cette matière n'est pas dans vos affectations.")
    return affectation


@permission_requise("evaluations.saisir")
def mes_evaluations(request):
    if request.appartenance is None:
        return render(request, "404.html", status=404)

    annee = annee_active(request.etablissement)
    periodes = list(annee.periodes.all()) if annee else []
    lignes = []
    for affectation in request.appartenance.affectations.select_related("matiere_niveau__matiere", "matiere_niveau__niveau", "classe"):
        if annee and affectation.matiere_niveau.annee_id != annee.pk:
            continue
        configurations = {c.periode_id: c for c in ConfigurationEvaluation.objects.filter(affectation=affectation)}
        lignes.append({"affectation": affectation, "periodes": [(p, configurations.get(p.pk)) for p in periodes]})
    return render(request, "evaluations/mes_evaluations.html", {"lignes": lignes, "annee": annee})


@permission_requise("evaluations.saisir", "resultats.consulter", "resultats.consulter_tous")
def classes(request):
    """Classes et matières de l'enseignant connecté (ou de tous pour la direction)."""
    annee = annee_active(request.etablissement)
    affectations = services.affectations_visibles(request.appartenance) if request.appartenance else AffectationEnseignant.objects.none()
    if annee:
        affectations = affectations.filter(matiere_niveau__annee=annee)
    return render(request, "evaluations/classes.html", {"affectations": affectations, "annee": annee})


@permission_requise("evaluations.saisir")
def configuration(request, affectation_pk, periode_pk):
    affectation = _affectation_autorisee(request, affectation_pk)
    periode = get_object_or_404(Periode, pk=periode_pk)
    try:
        config = services.creer_configuration(affectation, periode, par=request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
        return redirect("evaluations:mes_evaluations")
    bareme = services.bareme_de_configuration(config)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action in ("enregistrer", "valider"):
                intitules = request.POST.getlist("intitule")
                baremes = request.POST.getlist("bareme")
                composantes = [(i, b) for i, b in zip(intitules, baremes) if i.strip() or str(b).strip()]
                services.definir_composantes(
                    config, composantes, par=request.user,
                    confirmer_perte_notes=request.POST.get("confirmer_perte") == "1",
                )
                if action == "valider":
                    services.valider_configuration(config, par=request.user)
                    messages.success(request, "Configuration validée : vous pouvez saisir les notes.")
                    return redirect("evaluations:saisie", config.pk)
                messages.success(request, "Brouillon enregistré.")
            elif action == "rouvrir":
                services.rouvrir_configuration(config, request.POST.get("motif", ""), par=request.user)
                messages.success(request, "Configuration rouverte.")
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
        return redirect("evaluations:configuration", affectation.pk, periode.pk)

    config.refresh_from_db()
    return render(request, "evaluations/configuration.html", {
        "config": config, "affectation": affectation, "periode": periode, "bareme": bareme,
        "composantes": list(config.composantes.all()), "somme": services.somme_composantes(config),
        "notes_existantes": Note.objects.filter(composante__configuration=config).exists(),
    })


@permission_requise("evaluations.saisir")
def saisie(request, pk):
    config = get_object_or_404(
        ConfigurationEvaluation.objects.select_related("affectation__matiere_niveau__matiere", "affectation__classe", "periode"), pk=pk
    )
    _affectation_autorisee(request, config.affectation_id)
    composantes = list(config.composantes.all())
    inscriptions = list(services.inscriptions_concernees(config))
    if request.method == "POST":
        saisies = []
        for inscription in inscriptions:
            for composante in composantes:
                cle = f"{inscription.pk}_{composante.pk}"
                etat = request.POST.get(f"etat_{cle}", "SAISIE")
                saisies.append({
                    "inscription_id": inscription.pk, "composante_id": composante.pk,
                    "valeur": request.POST.get(f"note_{cle}", ""), "etat": etat,
                })
        try:
            crees, modifiees = services.saisir_notes(config, saisies, request.appartenance, motif=request.POST.get("motif", ""))
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
        else:
            messages.success(request, f"Notes enregistrées ({crees} ajoutée(s), {modifiees} modifiée(s)). Résultats recalculés.")
            return redirect("evaluations:saisie", config.pk)
    notes = {(n.inscription_id, n.composante_id): n for n in Note.objects.filter(composante__configuration=config)}
    resultats = {r.inscription_id: r for r in services.resultats_de_configuration(config)}
    lignes = [
        {"inscription": i, "resultat": resultats.get(i.pk),
         "cellules": [{"composante": c, "note": notes.get((i.pk, c.pk)), "cle": f"{i.pk}_{c.pk}"} for c in composantes]}
        for i in inscriptions
    ]
    return render(request, "evaluations/saisie.html", {
        "config": config, "composantes": composantes, "lignes": lignes,
        "saisie_possible": config.statut == "VALIDEE" and config.periode.saisie_ouverte and config.periode.statut == "OUVERTE",
        "publie": any(r.publie for r in resultats.values()),
    })


@permission_requise("resultats.publier", "evaluations.saisir")
def synthese(request, pk):
    """Indicateurs de classe, publication et dépublication des résultats."""
    config = get_object_or_404(
        ConfigurationEvaluation.objects.select_related("affectation__matiere_niveau__matiere", "affectation__classe", "periode"), pk=pk
    )
    peut_publier = a_la_permission(request, "resultats.publier") or config.affectation.appartenance_id == getattr(request.appartenance, "pk", None)
    if config.affectation.appartenance_id != getattr(request.appartenance, "pk", None) and not a_la_permission(request, "resultats.consulter_tous"):
        raise PermissionDenied("Vous ne pouvez pas consulter cette évaluation.")
    if request.method == "POST":
        if not peut_publier:
            raise PermissionDenied("Vous n'avez pas l'autorisation de publier.")
        try:
            if request.POST.get("action") == "publier":
                publies, incomplets = services.publier_resultats(config, request.user, forcer=request.POST.get("forcer") == "1")
                messages.success(request, f"{publies} résultat(s) publié(s).")
            elif request.POST.get("action") == "depublier":
                services.depublier_resultats(config, request.user, request.POST.get("motif", ""))
                messages.success(request, "Résultats dépubliés.")
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
        return redirect("evaluations:synthese", config.pk)
    services.calculer_resultats(config) if config.statut != "BROUILLON" else None
    return render(request, "evaluations/synthese.html", {
        "config": config, "stats": services.statistiques_configuration(config),
        "resultats": services.resultats_de_configuration(config).select_related("inscription__apprenant"),
        "peut_publier": peut_publier,
    })


def _lignes_export(resultats, classement_autorise=False):
    resultats = list(resultats)
    entetes = ["Apprenant", "Matricule", "Classe"]
    rangs = services.rangs_par_resultat(resultats) if classement_autorise else {}
    if classement_autorise:
        entetes.append("Rang")
    entetes.extend(["Matière", "Période", "Total", "Barème", "%", "Statut", "Publié"])
    lignes = []
    for resultat in resultats:
        ligne = [
            str(resultat.inscription.apprenant), resultat.inscription.apprenant.matricule,
            str(resultat.inscription.classe or ""),
        ]
        if classement_autorise:
            ligne.append(rangs.get(resultat.pk) or "-")
        ligne.extend([
            str(resultat.matiere_niveau.matiere), resultat.periode.nom,
            services.formater(resultat.total), services.formater(resultat.bareme_applique),
            services.formater(resultat.pourcentage), resultat.get_statut_display(),
            "Oui" if resultat.publie else "Non",
        ])
        lignes.append(ligne)
    return entetes, lignes


def _lignes_bulletins_export(bulletins, classement_autorise):
    entetes = ["Apprenant", "Matricule", "Classe", "Matières comptées", "Matières attendues", "Moyenne", "Statut"]
    if classement_autorise:
        entetes.insert(3, "Rang")
    lignes = []
    for bulletin in bulletins:
        inscription = bulletin["inscription"]
        moyenne = bulletin["moyenne"]
        ligne = [
            str(inscription.apprenant), inscription.apprenant.matricule, str(inscription.classe or ""),
            bulletin["matieres_comptees"], bulletin["matieres_attendues"],
            f'{services.formater(moyenne["moyenne"])}/{moyenne["echelle"]}' if moyenne else "-",
            "Complet" if bulletin["complet"] else "Incomplet",
        ]
        if classement_autorise:
            ligne.insert(3, bulletin["rang"] or "-")
        lignes.append(ligne)
    return entetes, lignes


@permission_requise("resultats.consulter", "resultats.consulter_tous")
def resultats(request):
    vue = request.GET.get("vue", "matieres")
    if vue not in ("matieres", "bulletin"):
        vue = "matieres"
    peut_consulter_tous = a_la_permission(request, "resultats.consulter_tous")
    if vue == "bulletin" and not peut_consulter_tous:
        raise PermissionDenied("Le bulletin synthétique est réservé aux personnes autorisées à consulter tous les résultats.")
    filtres = {c: request.GET.get(c, "") for c in (
        "annee", "periode", "niveau", "classe", "matiere", "composante", "statut", "publie", "apprenant",
    )}
    parametres_etablissement = ParametresEtablissement.objects.filter(etablissement=request.etablissement).first()
    classement_autorise = bool(parametres_etablissement and parametres_etablissement.classement_autorise)
    periode_bulletin = Periode.objects.filter(pk=filtres["periode"]).first() if filtres["periode"] else None
    if vue == "bulletin":
        bulletins = services.bulletins_synthetiques(periode_bulletin, filtres) if periode_bulletin else []
        matieres_bulletin = {
            matiere.pk: matiere
            for bulletin in bulletins
            for matiere in bulletin["matieres_bulletin"]
        }
        matieres_bulletin = sorted(matieres_bulletin.values(), key=lambda matiere: matiere.nom.casefold())
        baremes_vus = {}
        for bulletin in bulletins:
            for matiere_id, bareme in bulletin["baremes_par_matiere"].items():
                baremes_vus.setdefault(matiere_id, set()).add(bareme)
        baremes_bulletin = {
            matiere_id: next(iter(baremes)) if len(baremes) == 1 else None
            for matiere_id, baremes in baremes_vus.items()
        }
        for bulletin in bulletins:
            notes_matieres = {}
            for matiere in matieres_bulletin:
                resultat = bulletin["resultats_par_matiere"].get(matiere.pk)
                if resultat is None:
                    notes_matieres[matiere.pk] = None
                elif resultat.pourcentage is None or resultat.statut == ResultatPeriode.Statut.INCOMPLET:
                    notes_matieres[matiere.pk] = {"statut": resultat.get_statut_display()}
                else:
                    notes_matieres[matiere.pk] = {
                        "total": resultat.total,
                        "bareme": resultat.bareme_applique,
                    }
            bulletin["notes_matieres"] = notes_matieres
        if periode_bulletin and bulletins:
            inscription_ids = [bulletin["inscription"].pk for bulletin in bulletins]
            documents_par_inscription = {}
            for document in DocumentResultat.objects.filter(
                inscription_id__in=inscription_ids, periode=periode_bulletin
            ):
                documents_par_inscription.setdefault(document.inscription_id, []).append(document)
            for bulletin in bulletins:
                bulletin["documents"] = documents_par_inscription.get(
                    bulletin["inscription"].pk, []
                )
                bulletin["document_actif"] = next(
                    (document for document in bulletin["documents"] if document.est_valide), None
                )
        if classement_autorise:
            bulletins = sorted(
                bulletins,
                key=lambda bulletin: (
                    bulletin["rang"] is None,
                    bulletin["rang"] or 0,
                    bulletin["inscription"].apprenant.nom.casefold(),
                    bulletin["inscription"].apprenant.prenoms.casefold(),
                ),
            )
        else:
            bulletins = sorted(
                bulletins,
                key=lambda bulletin: (
                    not bulletin["complet"],
                    -(bulletin["moyenne"]["pourcentage"] if bulletin["moyenne"] else 0),
                    bulletin["inscription"].apprenant.nom.casefold(),
                    bulletin["inscription"].apprenant.prenoms.casefold(),
                ),
            )
        export = request.GET.get("export")
        if export in ("excel", "pdf"):
            if not a_la_permission(request, "resultats.exporter"):
                raise PermissionDenied("Vous n'avez pas l'autorisation d'exporter.")
            if periode_bulletin is None:
                raise PermissionDenied("Sélectionnez une période avant d'exporter le bulletin.")
            entetes, lignes = _lignes_bulletins_export(bulletins, classement_autorise)
            if export == "excel":
                reponse = HttpResponse(
                    exporter_excel("Bulletins", entetes, lignes),
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                reponse["Content-Disposition"] = 'attachment; filename="bulletins.xlsx"'
            else:
                reponse = HttpResponse(
                    exporter_pdf(f"Bulletins · {periode_bulletin}", entetes, lignes),
                    content_type="application/pdf",
                )
                reponse["Content-Disposition"] = 'attachment; filename="bulletins.pdf"'
            return reponse
        parametres = "&".join(f"{k}={v}" for k, v in filtres.items() if v)
        if vue:
            parametres = f"{parametres}&vue=bulletin" if parametres else "vue=bulletin"
        return render(request, "evaluations/resultats.html", {
            "vue": vue, "bulletins": bulletins, "periode_bulletin": periode_bulletin,
            "matieres_bulletin": matieres_bulletin, "baremes_bulletin": baremes_bulletin,
            "filtres": filtres, "parametres": parametres + "&" if parametres else "",
            "annees": AnneeAcademique.objects.all(), "niveaux": Niveau.objects.all(),
            "classes": Classe.objects.all(), "matieres": Matiere.objects.all(),
            "composantes": ComposanteEvaluation.objects.none(),
            "periodes": Periode.objects.select_related("annee"),
            "statuts": ResultatPeriode.Statut.choices, "peut_exporter": a_la_permission(request, "resultats.exporter"),
            "classement_autorise": classement_autorise, "peut_consulter_tous": peut_consulter_tous,
            "peut_configurer": a_la_permission(request, "etablissement.configurer"),
        })

    requete = services.resultats_visibles(request.user, request.appartenance, filtres)
    configurations = ConfigurationEvaluation.objects.all()
    if not a_la_permission(request, "resultats.consulter_tous"):
        configurations = configurations.filter(affectation__appartenance=request.appartenance)
    composantes = ComposanteEvaluation.objects.filter(
        configuration__in=configurations
    ).select_related(
        "configuration__affectation__matiere_niveau__matiere", "configuration__periode"
    ).order_by(
        "configuration__periode__annee__date_debut",
        "configuration__periode__ordre",
        "configuration__affectation__matiere_niveau__matiere__nom",
        "ordre",
    )
    export = request.GET.get("export")
    if export in ("excel", "pdf"):
        if not a_la_permission(request, "resultats.exporter"):
            raise PermissionDenied("Vous n'avez pas l'autorisation d'exporter.")
        entetes, lignes = _lignes_export(requete, classement_autorise)
        if export == "excel":
            reponse = HttpResponse(exporter_excel("Résultats", entetes, lignes),
                                   content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            reponse["Content-Disposition"] = 'attachment; filename="resultats.xlsx"'
        else:
            reponse = HttpResponse(exporter_pdf("Résultats", entetes, lignes), content_type="application/pdf")
            reponse["Content-Disposition"] = 'attachment; filename="resultats.pdf"'
        return reponse
    parametres = "&".join(f"{k}={v}" for k, v in filtres.items() if v)
    page = Paginator(requete, 25).get_page(request.GET.get("page"))
    rangs = services.rangs_par_resultat(page.object_list) if classement_autorise else {}
    for resultat in page.object_list:
        resultat.rang = rangs.get(resultat.pk)
    if vue:
        parametres = f"{parametres}&vue=matieres" if parametres else "vue=matieres"
    return render(request, "evaluations/resultats.html", {
        "vue": vue,
        "page": page, "filtres": filtres, "parametres": parametres + "&" if parametres else "",
        "annees": AnneeAcademique.objects.all(), "niveaux": Niveau.objects.all(), "classes": Classe.objects.all(),
        "matieres": Matiere.objects.all(), "composantes": composantes,
        "periodes": Periode.objects.select_related("annee"),
        "statuts": ResultatPeriode.Statut.choices, "peut_exporter": a_la_permission(request, "resultats.exporter"),
        "classement_autorise": classement_autorise, "peut_consulter_tous": peut_consulter_tous,
        "peut_configurer": a_la_permission(request, "etablissement.configurer"),
    })


@permission_requise("resultats.consulter_propres", "resultats.consulter_enfants")
def portail(request):
    liste = services.resultats_portail(request.user)
    par_apprenant = {}
    for r in liste:
        par_apprenant.setdefault(r.inscription.apprenant, []).append(r)
    if liste:
        inscription_ids = {resultat.inscription_id for resultat in liste}
        periode_ids = {resultat.periode_id for resultat in liste}
        documents = DocumentResultat.objects.filter(
            inscription_id__in=inscription_ids, periode_id__in=periode_ids,
            revoque_le__isnull=True,
        )
        documents_par_cle = {
            (document.inscription_id, document.periode_id): document
            for document in reversed(list(documents))
        }
        for resultats_apprenant in par_apprenant.values():
            for resultat in resultats_apprenant:
                resultat.document_resultat = documents_par_cle.get(
                    (resultat.inscription_id, resultat.periode_id)
                )
    return render(request, "evaluations/portail.html", {"par_apprenant": par_apprenant})


@permission_requise("resultats.consulter_tous")
@require_POST
def creer_document_resultat(request, inscription_pk, periode_pk):
    inscription = get_object_or_404(Inscription.objects.select_related("apprenant"), pk=inscription_pk)
    periode = get_object_or_404(Periode, pk=periode_pk)
    try:
        document = services.generer_document_resultat(inscription, periode, request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, f"Document de résultats version {document.version} créé.")
    return redirect(f"{reverse('evaluations:resultats')}?vue=bulletin&periode={periode.pk}")


@permission_requise("resultats.consulter_tous")
@require_POST
def revoquer_document_resultat(request, pk):
    document = get_object_or_404(DocumentResultat, pk=pk)
    periode_pk = document.periode_id
    try:
        services.revoquer_document_resultat(
            document, request.POST.get("motif", ""), request.user
        )
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Document de résultats révoqué.")
    return redirect(f"{reverse('evaluations:resultats')}?vue=bulletin&periode={periode_pk}")


@permission_requise(
    "resultats.consulter_tous", "resultats.consulter_propres", "resultats.consulter_enfants"
)
def telecharger_document_resultat(request, pk):
    document = get_object_or_404(DocumentResultat, pk=pk, revoque_le__isnull=True)
    if not a_la_permission(request, "resultats.consulter_tous") and not services.resultats_portail(
        request.user
    ).filter(inscription=document.inscription, periode=document.periode).exists():
        raise PermissionDenied("Ce document n'est pas accessible depuis votre portail de résultats.")
    if not document.fichier:
        raise Http404
    return FileResponse(
        document.fichier.open("rb"),
        as_attachment=True,
        filename=f"resultats-v{document.version}.pdf",
    )


@permission_requise("examens.consulter", "examens.gerer")
def examens(request):
    annee = annee_active(request.etablissement)
    peut_gerer = a_la_permission(request, "examens.gerer")
    liste_examens = Examen.objects.none()
    if annee is not None:
        liste_examens = Examen.objects.filter(
            matiere_niveau__annee=annee
        ).select_related(
            "matiere_niveau__matiere", "matiere_niveau__niveau", "classe", "salle"
        )
    examens_planifies = liste_examens.filter(statut=Examen.Statut.PLANIFIE).count()
    examens_annules = liste_examens.filter(statut=Examen.Statut.ANNULE).count()
    return render(request, "evaluations/examens.html", {
        "examens": liste_examens,
        "annee": annee,
        "peut_gerer": peut_gerer,
        "examens_planifies": examens_planifies,
        "examens_annules": examens_annules,
    })


@permission_requise("examens.gerer")
def examen_creer(request):
    annee = annee_active(request.etablissement)
    if annee is None:
        messages.error(request, "Activez une année académique avant de planifier un examen.")
        return redirect("evaluations:examens")
    formulaire = FormulaireExamen(
        request.POST or None, etablissement=request.etablissement, annee=annee
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.planifier_examen(
                etablissement=request.etablissement,
                par=request.user,
                **formulaire.cleaned_data,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Examen planifié.")
            return redirect("evaluations:examens")
    return render(request, "evaluations/examen_form.html", {"formulaire": formulaire})


@permission_requise("examens.gerer")
def examen_modifier(request, pk):
    examen = get_object_or_404(
        Examen.objects.select_related("matiere_niveau__annee"), pk=pk
    )
    annee = annee_active(request.etablissement)
    if annee is None or examen.matiere_niveau.annee_id != annee.pk:
        messages.error(request, "Seuls les examens de l'année académique active peuvent être modifiés.")
        return redirect("evaluations:examens")
    formulaire = FormulaireExamen(
        request.POST or None, instance=examen,
        etablissement=request.etablissement, annee=annee,
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.modifier_examen(
                examen, par=request.user, **formulaire.cleaned_data
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            messages.success(request, "Examen mis à jour.")
            return redirect("evaluations:examens")
    return render(request, "evaluations/examen_form.html", {
        "formulaire": formulaire, "examen": examen,
    })


@permission_requise("examens.gerer")
@require_POST
def examen_annuler(request, pk):
    examen = get_object_or_404(Examen.objects, pk=pk)
    try:
        services.annuler_examen(examen, request.user)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Examen annulé.")
    return redirect("evaluations:examens")
