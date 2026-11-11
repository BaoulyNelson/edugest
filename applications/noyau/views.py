from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from applications.comptes.forms import FormulaireInvitation
from applications.academique.services import annee_active, configuration_rapide
from .decorateurs import a_la_permission, permission_requise
from .exceptions import ErreurMetier
from .forms import (
    FormulaireConfigurationPlateforme, FormulaireDemarrage, FormulaireIdentite, FormulaireNotation,
    FormulairePeriodes, FormulaireNouvelEspace, FormulaireProvisionnement, FormulaireRetention,
)
from .models import (
    Abonnement, Appartenance, ConfigurationPlateforme, Etablissement, Invitation, JournalAudit,
    ParametresEtablissement, Plan, Role, TypeEtablissement,
    UsageAbonnement, Utilisateur, VocabulaireInstitutionnel,
)
from . import saas
from .services import VOCABULAIRE_PAR_TYPE, vocabulaire

def url_base(request):
    return request.build_absolute_uri("/").rstrip("/")


def accueil_public(request):
    return render(request, "noyau/accueil_public.html", {
        "plans": [saas.obtenir_plan(code) for code in saas.PLANS_PAR_DEFAUT],
    })


@require_POST
def choisir_langue(request):
    langues = {code for code, _ in settings.LANGUAGES}
    langue = request.POST.get("langue", "")
    if not langue:
        request.session.pop("langue_interface", None)
    elif langue in langues:
        request.session["langue_interface"] = langue
    else:
        messages.error(request, _("La langue sélectionnée n’est pas disponible."))
    destination = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        destination = "/"
    return redirect(destination)


def administrateur_plateforme_requis(vue):
    @login_required
    def enveloppe(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Réservé à l'administrateur de la plateforme.")
        return vue(request, *args, **kwargs)

    enveloppe.__name__ = vue.__name__
    return enveloppe


# ------------------------------------------------------------------ tableau de bord


def _etapes_demarrage(etablissement):
    from applications.academique.models import Niveau
    from applications.apprenants.models import Apprenant
    from applications.pedagogie.models import MatiereNiveau

    return [
        ("Activer l'année académique et ses périodes", annee_active(etablissement) is not None, "demarrage"),
        ("Définir les niveaux et les classes", Niveau.objects.filter(etablissement=etablissement).exists(), "academique:structure"),
        ("Configurer les matières et leurs barèmes",
         MatiereNiveau.objects.filter(annee__etablissement=etablissement).exists(), "pedagogie:matieres"),
        ("Inviter l'équipe (secrétaires, enseignants…)",
         Invitation.objects.filter(etablissement=etablissement).exists()
         or Appartenance.objects.filter(etablissement=etablissement).count() > 1, "personnel"),
        ("Enregistrer les premiers apprenants", Apprenant.objects.filter(etablissement=etablissement).exists(), "apprenants:creer"),
    ]


def _graphique_repartition_apprenants(etablissement, annee):
    from applications.apprenants.models import Inscription

    lignes = Inscription.objects.filter(
        etablissement=etablissement, annee=annee, statut=Inscription.Statut.VALIDEE,
    ).values(
        "classe_id", "classe__nom", "niveau__nom", "niveau__ordre", "niveau__programme__nom",
    ).annotate(total=Count("pk")).order_by(
        "niveau__programme__nom", "niveau__ordre", "niveau__nom", "classe__nom",
    )
    return {
        "labels": [
            " · ".join(partie for partie in (
                ligne["niveau__programme__nom"], ligne["niveau__nom"],
                ligne["classe__nom"] if ligne["classe_id"] else None,
            ) if partie)
            for ligne in lignes
        ],
        "values": [ligne["total"] for ligne in lignes],
        "series_label": _("Apprenants"),
    }


def _graphique_statuts_paiement(etablissement, annee):
    from decimal import Decimal

    from django.db.models import Prefetch

    from applications.apprenants.models import Inscription
    from applications.finances.models import Echeance, Facture, Paiement, Remboursement

    paiements = Paiement.objects.prefetch_related(
        Prefetch("remboursements", queryset=Remboursement.objects.all())
    )
    factures = Facture.objects.filter(
        etablissement=etablissement, inscription__annee=annee,
        inscription__statut=Inscription.Statut.VALIDEE,
    ).exclude(statut=Facture.Statut.ANNULEE).prefetch_related(
        Prefetch("echeances", queryset=Echeance.objects.order_by("date_limite", "ordre", "pk")),
        Prefetch("paiements", queryset=paiements),
    )
    aujourd_hui = timezone.localdate()
    categories = (_("Payé"), _("En retard"), _("Partiel"), _("À venir"))
    comptes = dict.fromkeys(categories, 0)
    for facture in factures:
        total_paye = sum(
            (
                paiement.montant - sum(
                    (remboursement.montant for remboursement in paiement.remboursements.all()),
                    Decimal("0"),
                )
                for paiement in facture.paiements.all()
            ),
            Decimal("0"),
        )
        if total_paye >= facture.total:
            comptes["Payé"] += 1
            continue

        restant_a_imputer = total_paye
        en_retard = False
        for echeance in facture.echeances.all():
            paye = min(restant_a_imputer, echeance.montant)
            restant_a_imputer -= paye
            if echeance.date_limite < aujourd_hui and echeance.montant - paye > 0:
                en_retard = True
        if en_retard:
            comptes["En retard"] += 1
        elif total_paye > 0:
            comptes["Partiel"] += 1
        else:
            comptes["À venir"] += 1

    return {"labels": list(comptes), "values": list(comptes.values())}


def _graphique_moyennes_periodes(etablissement, annee):
    from decimal import Decimal

    from applications.apprenants.models import Inscription
    from applications.evaluations.models import ResultatPeriode
    from applications.noyau.models import ParametresEtablissement
    from applications.pedagogie.models import DerogationClasse

    periodes = list(annee.periodes.order_by("ordre", "pk"))
    labels = [periode.nom for periode in periodes]
    if not periodes:
        return {"labels": [], "values": [], "echelle": 20, "series_label": _("Moyenne générale")}

    inscriptions = list(Inscription.objects.filter(
        etablissement=etablissement, annee=annee, statut=Inscription.Statut.VALIDEE,
    ).values_list("pk", "classe_id"))
    inscription_ids = [identifiant for identifiant, _ in inscriptions]
    inscriptions_par_classe = dict(inscriptions)
    resultat_lignes = list(ResultatPeriode.objects.filter(
        etablissement=etablissement, inscription_id__in=inscription_ids,
        periode_id__in=[periode.pk for periode in periodes], publie=True,
        statut__in=[ResultatPeriode.Statut.REUSSI, ResultatPeriode.Statut.ECHEC],
    ).values_list(
        "inscription_id", "periode_id", "matiere_niveau_id", "pourcentage",
        "matiere_niveau__coefficient",
    ))

    derogations = DerogationClasse.objects.filter(
        etablissement=etablissement,
        classe_id__in={classe_id for classe_id in inscriptions_par_classe.values() if classe_id},
        matiere_niveau_id__in={ligne[2] for ligne in resultat_lignes},
        coefficient__isnull=False,
    ).values_list("classe_id", "matiere_niveau_id", "coefficient")
    coefficients_derogatoires = {
        (classe_id, matiere_niveau_id): coefficient
        for classe_id, matiere_niveau_id, coefficient in derogations
    }

    cumuls = {}
    for inscription_id, periode_id, matiere_niveau_id, pourcentage, coefficient_defaut in resultat_lignes:
        classe_id = inscriptions_par_classe[inscription_id]
        coefficient = coefficients_derogatoires.get(
            (classe_id, matiere_niveau_id), coefficient_defaut,
        )
        cle = (inscription_id, periode_id)
        somme, poids = cumuls.get(cle, (Decimal("0"), Decimal("0")))
        cumuls[cle] = (somme + pourcentage * coefficient, poids + coefficient)

    moyennes_par_periode = {periode.pk: [] for periode in periodes}
    parametres = ParametresEtablissement.objects.filter(etablissement=etablissement).first()
    echelle = parametres.echelle_moyenne if parametres else 20
    for (_identifiant_inscription, periode_id), (somme, poids) in cumuls.items():
        if poids:
            pourcentage = (somme / poids).quantize(Decimal("0.01"))
            moyennes_par_periode[periode_id].append(
                (pourcentage * echelle / 100).quantize(Decimal("0.01"))
            )
    valeurs = []
    for periode in periodes:
        moyennes = moyennes_par_periode[periode.pk]
        valeurs.append(
            float((sum(moyennes, Decimal("0")) / len(moyennes)).quantize(Decimal("0.01")))
            if moyennes else None
        )
    return {
        "labels": labels, "values": valeurs, "echelle": echelle,
        "series_label": _("Moyenne générale"),
    }


@login_required
def tableau_de_bord(request):
    """Accueil adapté au rôle : seules les cartes autorisées par les permissions s'affichent."""
    if request.etablissement is None:
        if request.user.is_superuser:
            return redirect("plateforme")
        return redirect("etablissements")
    contexte = {
        "annee": annee_active(request.etablissement),
        "indicateurs": [],
        "taches": [],
        "resultats_recents": [],
        "etapes": [],
        "graphique_inscriptions": [],
        "profil_apprenant": False,
        "inscriptions_apprenant": [],
        "graphique_devoirs": [],
        "devoirs_corriges_recents": [],
        "graphiques_tableau": {},
    }
    from applications.apprenants.models import Apprenant, Inscription, LienResponsable
    from applications.evaluations import services as evaluations

    if contexte["annee"]:
        graphiques = contexte["graphiques_tableau"]
        if (
            a_la_permission(request, "apprenants.consulter")
            or a_la_permission(request, "statistiques.consulter")
        ):
            graphiques["effectifs"] = _graphique_repartition_apprenants(
                request.etablissement, contexte["annee"],
            )
        if (
            a_la_permission(request, "finances.consulter")
            or a_la_permission(request, "statistiques.consulter")
        ):
            graphiques["paiements"] = _graphique_statuts_paiement(
                request.etablissement, contexte["annee"],
            )
        if (
            a_la_permission(request, "resultats.consulter_tous")
            or a_la_permission(request, "statistiques.consulter")
        ):
            graphiques["moyennes"] = _graphique_moyennes_periodes(
                request.etablissement, contexte["annee"],
            )
    if a_la_permission(request, "etablissement.configurer"):
        etapes = _etapes_demarrage(request.etablissement)
        if not all(fait for _, fait, _ in etapes):
            contexte["etapes"] = etapes
            contexte["etapes_faites"] = sum(1 for _, fait, _ in etapes if fait)
    if a_la_permission(request, "inscriptions.decider"):
        en_attente = Inscription.objects.filter(statut="EN_ATTENTE").count()
        contexte["indicateurs"].append(("En attente de décision", en_attente, "apprenants:inscriptions", "?statut=EN_ATTENTE"))
        from applications.admissions.models import Candidature

        candidatures = Candidature.objects.filter(statut=Candidature.Statut.RECUE).count()
        contexte["indicateurs"].append(("Candidatures à examiner", candidatures, "admissions:liste", "?statut=RECUE"))
        if contexte["annee"]:
            statuts_inscriptions = (
                ("Validées", Inscription.Statut.VALIDEE),
                ("En attente", Inscription.Statut.EN_ATTENTE),
                ("À compléter", Inscription.Statut.CORRECTION_DEMANDEE),
                ("Refusées", Inscription.Statut.REJETEE),
            )
            comptes = {
                statut: Inscription.objects.filter(annee=contexte["annee"], statut=statut).count()
                for _, statut in statuts_inscriptions
            }
            total = sum(comptes.values())
            contexte["graphique_inscriptions"] = [
                {
                    "libelle": libelle,
                    "valeur": comptes[statut],
                    "pourcentage": round(comptes[statut] * 100 / total) if total else 0,
                }
                for libelle, statut in statuts_inscriptions
            ]
    if a_la_permission(request, "apprenants.consulter") or a_la_permission(request, "statistiques.consulter"):
        contexte["indicateurs"].append(("Apprenants actifs", Apprenant.objects.filter(actif=True).count(), "apprenants:liste", ""))
        if contexte["annee"]:
            contexte["indicateurs"].append(
                ("Inscriptions validées", Inscription.objects.filter(annee=contexte["annee"], statut="VALIDEE").count(),
                 "apprenants:inscriptions", "?statut=VALIDEE"))
    if a_la_permission(request, "evaluations.saisir") and request.appartenance:
        from applications.evaluations.models import ConfigurationEvaluation

        affectations = request.appartenance.affectations.select_related("matiere_niveau__matiere", "classe", "matiere_niveau__niveau")
        for affectation in affectations:
            if contexte["annee"] and affectation.matiere_niveau.annee_id != contexte["annee"].pk:
                continue
            for periode in contexte["annee"].periodes.filter(statut="OUVERTE") if contexte["annee"] else []:
                configuration = ConfigurationEvaluation.objects.filter(affectation=affectation, periode=periode).first()
                contexte["taches"].append({"affectation": affectation, "periode": periode, "configuration": configuration})
    if a_la_permission(request, "resultats.consulter_propres") or a_la_permission(request, "resultats.consulter_enfants"):
        contexte["resultats_recents"] = list(evaluations.resultats_portail(request.user)[:6])
    compte_portail_lie = (
        Apprenant.objects.filter(
            etablissement=request.etablissement, utilisateur=request.user,
        ).exists()
        or LienResponsable.objects.filter(
            etablissement=request.etablissement, responsable__utilisateur=request.user,
        ).exists()
    )
    if a_la_permission(request, "devoirs.remettre") and compte_portail_lie:
        from applications.cahier import services as cahier_services
        from applications.cahier.models import Devoir, NotificationCahier, Remise

        inscriptions = cahier_services.inscriptions_de_l_utilisateur(
            request.user, request.etablissement,
        )
        if contexte["annee"]:
            inscriptions = inscriptions.filter(annee=contexte["annee"])
        contexte["inscriptions_apprenant"] = list(
            inscriptions.select_related("annee", "niveau", "classe__niveau", "programme")
            .order_by("apprenant__nom", "apprenant__prenoms")
        )
        contexte["profil_apprenant"] = True
        inscription_ids = [inscription.pk for inscription in contexte["inscriptions_apprenant"]]
        classe_ids = {
            inscription.classe_id
            for inscription in contexte["inscriptions_apprenant"]
            if inscription.classe_id
        }
        devoirs = list(
            Devoir.objects.filter(classe_id__in=classe_ids)
            .select_related("classe", "matiere_niveau__matiere")
            .order_by("date_limite", "heure_limite", "pk")
        )
        remises = {
            (remise.devoir_id, remise.inscription_id): remise
            for remise in Remise.objects.filter(
                inscription_id__in=inscription_ids,
                devoir_id__in=[devoir.pk for devoir in devoirs],
            )
        }
        compteurs = {"A_FAIRE": 0, "EN_RETARD": 0, "RENDU": 0, "NOTE": 0}
        maintenant = timezone.now()
        for inscription in contexte["inscriptions_apprenant"]:
            for devoir in devoirs:
                if devoir.classe_id != inscription.classe_id:
                    continue
                remise = remises.get((devoir.pk, inscription.pk))
                statut = remise.statut if remise else (
                    "EN_RETARD" if maintenant > devoir.echeance else "A_FAIRE"
                )
                compteurs[statut] += 1
        total_devoirs = sum(compteurs.values())
        categories_devoirs = (
            ("À faire", "A_FAIRE"),
            ("En retard", "EN_RETARD"),
            ("Remis", "RENDU"),
            ("Corrigés", "NOTE"),
        )
        contexte["graphique_devoirs"] = [
            {
                "libelle": libelle,
                "valeur": compteurs[statut],
                "pourcentage": round(compteurs[statut] * 100 / total_devoirs) if total_devoirs else 0,
            }
            for libelle, statut in categories_devoirs
        ]
        notifications_non_lues = set(
            NotificationCahier.objects.filter(
                etablissement=request.etablissement,
                destinataire=request.user,
                lue=False,
            ).values_list("url", flat=True)
        )
        contexte["devoirs_corriges_recents"] = [
            {
                "remise": remise,
                "nouveau": f"/cahier/devoirs/{remise.devoir_id}/" in notifications_non_lues,
            }
            for remise in Remise.objects.filter(
                inscription_id__in=inscription_ids,
                note__isnull=False,
            ).select_related(
                "devoir__matiere_niveau__matiere", "inscription__apprenant",
            ).order_by("-corrige_le", "-pk")[:5]
        ]
    return render(request, "noyau/tableau_de_bord.html", contexte)


# ------------------------------------------------------------------ espaces (établissements) et compte


@login_required
def etablissements(request):
    """Mes établissements : changer d'espace ou en créer un nouveau en autonomie."""
    formulaire = FormulaireNouvelEspace(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        etablissement = saas.creer_espace(request.user, formulaire.cleaned_data["nom_etablissement"], formulaire.cleaned_data["type_etablissement"])
        request.session["etablissement_id"] = etablissement.pk
        messages.success(
            request,
            f"L'établissement « {etablissement.nom} » a été créé. Vous en êtes l'administrateur.",
        )
        return redirect("demarrage")
    liste = Etablissement.objects.filter(
        pk__in=Appartenance.sans_filtre.filter(utilisateur=request.user, actif=True).values("etablissement_id"), actif=True
    )
    return render(request, "noyau/etablissements.html", {"liste": liste, "formulaire": formulaire})


@login_required
@require_POST
def choisir_etablissement(request, pk=None):
    if pk is None:
        try:
            pk = int(request.POST.get("etablissement", ""))
        except (TypeError, ValueError):
            raise Http404("Établissement invalide.")
    etablissement = get_object_or_404(Etablissement, pk=pk, actif=True)
    autorise = Appartenance.sans_filtre.filter(
        utilisateur=request.user, etablissement=etablissement, actif=True
    ).exists()
    if not autorise:
        raise PermissionDenied("Vous n'appartenez pas à cet établissement.")
    request.session["etablissement_id"] = etablissement.pk
    return redirect("tableau_de_bord")


# ------------------------------------------------------------------ administration de l'établissement


@permission_requise("etablissement.configurer")
def demarrage(request):
    """Configuration rapide : année, périodes, niveaux et classes en une seule étape."""
    formulaire = FormulaireDemarrage(request.POST or None, etablissement=request.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        d = formulaire.cleaned_data
        try:
            configuration_rapide(
                request.etablissement, d["designation"], d["date_debut"], d["date_fin"], d["nombre_periodes"],
                niveaux_standards=d.get("niveaux_standards", False), classes_par_niveau=d.get("classes_par_niveau", 0),
                par=request.user,
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            request.etablissement.parametres.nombre_periodes_par_annee = d["nombre_periodes"]
            request.etablissement.parametres.save(update_fields=["nombre_periodes_par_annee"])
            messages.success(request, "Votre établissement est configuré. Prochaine étape : les matières et leurs barèmes.")
            return redirect("tableau_de_bord")
    deja_configure = annee_active(request.etablissement) is not None
    return render(request, "noyau/demarrage.html", {"formulaire": formulaire, "deja_configure": deja_configure})


def _formulaire_vocabulaire(etablissement, donnees=None):
    from django import forms as f

    class FormulaireVocabulaire(f.Form):
        pass

    cles = list(VOCABULAIRE_PAR_TYPE[etablissement.type])
    for cle in cles:
        FormulaireVocabulaire.base_fields[f"{cle}_singulier"] = f.CharField(label=f"{cle.capitalize()} (singulier)", max_length=100)
        FormulaireVocabulaire.base_fields[f"{cle}_pluriel"] = f.CharField(label=f"{cle.capitalize()} (pluriel)", max_length=100)
    initial = {}
    for cle in cles:
        initial[f"{cle}_singulier"] = vocabulaire(etablissement, cle)
        initial[f"{cle}_pluriel"] = vocabulaire(etablissement, cle, pluriel=True)
    return FormulaireVocabulaire(donnees, initial=initial, prefix="vocabulaire"), cles


@permission_requise("etablissement.configurer")
def parametres(request):
    etablissement = request.etablissement
    parametres_obj = ParametresEtablissement.objects.get(etablissement=etablissement)
    cible = request.POST.get("cible")
    identite = FormulaireIdentite(request.POST if cible == "identite" else None, request.FILES if cible == "identite" else None,
                                  instance=etablissement, prefix="identite")
    notation = FormulaireNotation(request.POST if cible == "notation" else None, instance=parametres_obj, prefix="notation")
    periodes = FormulairePeriodes(
        request.POST if cible == "periodes" else None, instance=parametres_obj, prefix="periodes"
    )
    retention = FormulaireRetention(
        request.POST if cible == "retention" else None, instance=parametres_obj, prefix="retention"
    )
    vocab, cles = _formulaire_vocabulaire(etablissement, request.POST if cible == "vocabulaire" else None)
    if request.method == "POST":
        if cible == "identite" and identite.is_valid():
            identite.save()
            messages.success(request, "Identité de l'établissement mise à jour.")
            return redirect("parametres")
        if cible == "notation" and notation.is_valid():
            notation.save()
            messages.success(request, "Règles de notation enregistrées.")
            return redirect("parametres")
        if cible == "periodes" and periodes.is_valid():
            periodes.save()
            messages.success(request, "Nombre de périodes par année enregistré.")
            return redirect("parametres")
        if cible == "retention" and retention.is_valid():
            retention.save()
            messages.success(request, "Durée de conservation des dossiers enregistrée.")
            return redirect("parametres")
        if cible == "vocabulaire" and vocab.is_valid():
            for cle in cles:
                VocabulaireInstitutionnel.sans_filtre.update_or_create(
                    etablissement=etablissement, cle=cle,
                    defaults={"libelle_singulier": vocab.cleaned_data[f"{cle}_singulier"], "libelle_pluriel": vocab.cleaned_data[f"{cle}_pluriel"]},
                )
            messages.success(request, "Vocabulaire enregistré.")
            return redirect("parametres")
    return render(request, "noyau/parametres.html", {
        "identite": identite, "notation": notation, "periodes": periodes, "retention": retention,
        "vocab": vocab, "cles": cles,
    })


@login_required
def abonnement(request):
    if request.etablissement is None:
        raise PermissionDenied("Aucun établissement sélectionné.")
    usage = saas.usage_abonnement(request.etablissement)
    saas.enregistrer_usage_abonnement(request.etablissement)
    historique_usage = UsageAbonnement.objects.filter(
        etablissement=request.etablissement
    ).order_by("-date")[:30]
    actif, message = saas.etat_abonnement(request.etablissement)
    return render(request, "noyau/abonnement.html", {
        "usage": usage, "actif": actif, "message": message,
        "plans": [saas.obtenir_plan(c) for c in saas.PLANS_PAR_DEFAUT],
        "historique_usage": historique_usage,
    })


@permission_requise("utilisateurs.gerer")
def personnel(request):
    formulaire = FormulaireInvitation(
        request.POST or None, prefix="invitation", etablissement=request.etablissement
    )
    if request.method == "POST" and formulaire.is_valid():
        d = formulaire.cleaned_data
        try:
            saas.inviter(
                request.etablissement, d["email"], d["role"], request.user, url_base(request),
                apprenant=d["apprenant"], responsable=d.get("responsable"),
            )
        except ErreurMetier as erreur:
            formulaire.add_error(None, str(erreur))
        else:
            if saas.courriel_en_mode_console():
                messages.warning(
                    request,
                    f"L'invitation pour {d['email']} a été créée, mais aucun e-mail n'a été livré : "
                    "le mode console affiche le message dans le terminal du serveur. Configurez SMTP pour l'envoyer.",
                )
            else:
                messages.success(
                    request, f"Invitation envoyée à {d['email']}. La personne créera elle-même son compte."
                )
            return redirect("personnel")
    membres = Appartenance.objects.select_related("utilisateur", "role").order_by("-actif", "role__nom", "utilisateur__last_name")
    invitations = Invitation.objects.select_related("role").filter(statut="EN_ATTENTE")
    roles = Role.objects.all()
    if request.etablissement.type != TypeEtablissement.SCOLAIRE:
        roles = roles.exclude(nom="Parent")
    return render(request, "noyau/personnel.html", {
        "membres": membres, "invitations": invitations, "formulaire": formulaire, "roles": roles,
    })


@permission_requise("utilisateurs.gerer")
@require_POST
def membre_action(request, pk):
    appartenance = get_object_or_404(Appartenance.objects.select_related("role", "utilisateur"), pk=pk)
    action = request.POST.get("action")
    try:
        if action == "role":
            role = get_object_or_404(Role, pk=request.POST.get("role"))
            saas.changer_role_membre(appartenance, role, request.user)
            messages.success(request, "Rôle modifié.")
        elif action in ("desactiver", "activer"):
            if appartenance.utilisateur_id == request.user.pk and action == "desactiver":
                raise ErreurMetier("Vous ne pouvez pas désactiver votre propre accès.")
            saas.basculer_membre(appartenance, action == "activer", request.user)
            messages.success(request, "Accès mis à jour.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("personnel")


@permission_requise("utilisateurs.gerer")
@require_POST
def invitation_action(request, pk):
    invitation_obj = get_object_or_404(Invitation, pk=pk)
    try:
        if request.POST.get("action") == "renvoyer":
            saas.renvoyer_invitation(invitation_obj, url_base(request))
            if saas.courriel_en_mode_console():
                messages.warning(
                    request,
                    "L'invitation a été renouvelée, mais aucun e-mail n'a été livré : "
                    "le message est affiché dans le terminal du serveur.",
                )
            else:
                messages.success(request, "Invitation renvoyée.")
        elif request.POST.get("action") == "revoquer":
            saas.revoquer_invitation(invitation_obj, request.user)
            messages.success(request, "Invitation révoquée.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("personnel")


@permission_requise("statistiques.consulter")
def rapports(request):
    from applications.apprenants.models import Inscription

    annee = annee_active(request.etablissement)
    repartition = []
    if annee:
        repartition = (
            Inscription.objects.filter(annee=annee, statut="VALIDEE")
            .values("niveau__nom", "classe__nom").annotate(effectif=Count("id")).order_by("niveau__ordre", "classe__nom")
        )
    return render(request, "noyau/rapports.html", {"annee": annee, "repartition": repartition})


# ------------------------------------------------------------------ console de la plateforme


@administrateur_plateforme_requis
def plateforme(request):
    from applications.apprenants.models import Apprenant

    provisionnement = FormulaireProvisionnement(
        request.POST if request.method == "POST" and request.POST.get("action") == "creer" else None,
        prefix="provisionnement",
    )
    if request.method == "POST" and request.POST.get("action") == "creer" and provisionnement.is_valid():
        donnees = provisionnement.cleaned_data
        try:
            etablissement = saas.creer_espace(
                donnees["administrateur"], donnees["nom_etablissement"], donnees["type_etablissement"],
                par=request.user,
            )
        except (ErreurMetier, ValueError) as erreur:
            provisionnement.add_error(None, str(erreur))
        else:
            messages.success(request, f"L'espace « {etablissement.nom} » a été créé et son administrateur désigné.")
            return redirect("plateforme")

    membres_par_etablissement = dict(
        Appartenance.sans_filtre.filter(actif=True).values("etablissement_id")
        .annotate(total=Count("pk")).values_list("etablissement_id", "total")
    )
    apprenants_par_etablissement = dict(
        Apprenant.sans_filtre.filter(actif=True).values("etablissement_id")
        .annotate(total=Count("pk")).values_list("etablissement_id", "total")
    )
    lignes = []
    for etablissement in Etablissement.objects.select_related("abonnement__plan").order_by("-cree_le"):
        lignes.append({
            "etablissement": etablissement, "abonnement": getattr(etablissement, "abonnement", None),
            "membres": membres_par_etablissement.get(etablissement.pk, 0),
            "apprenants": apprenants_par_etablissement.get(etablissement.pk, 0),
        })
    abonnements_par_statut = dict(
        Abonnement.objects.values_list("statut").annotate(total=Count("pk"))
    )
    audits_recents = JournalAudit.objects.select_related("etablissement", "utilisateur").order_by(
        "-date", "-pk"
    )[:50]
    actions_recentes = (
        JournalAudit.objects.filter(date__gte=timezone.now() - timedelta(days=30))
        .values("action").annotate(total=Count("pk")).order_by("-total", "action")[:5]
    )
    for code in saas.PLANS_PAR_DEFAUT:
        saas.obtenir_plan(code)
    return render(request, "noyau/plateforme.html", {
        "lignes": lignes, "plans": Plan.objects.all(),
        "statuts": Abonnement.Statut.choices, "total_utilisateurs": Utilisateur.objects.count(),
        "total_membres": sum(ligne["membres"] for ligne in lignes),
        "total_apprenants": sum(ligne["apprenants"] for ligne in lignes),
        "abonnements_par_statut": abonnements_par_statut,
        "audits_recents": audits_recents,
        "actions_recentes": actions_recentes,
        "provisionnement": provisionnement,
    })


@administrateur_plateforme_requis
@require_POST
def plateforme_action(request, pk):
    etablissement = get_object_or_404(Etablissement, pk=pk)
    try:
        saas.modifier_abonnement(
            etablissement, statut=request.POST.get("statut") or None, code_plan=request.POST.get("plan") or None, par=request.user
        )
        etat = request.POST.get("actif")
        if etat in ("0", "1"):
            saas.modifier_etat_etablissement(etablissement, etat == "1", par=request.user)
        messages.success(request, f"Paramètres de « {etablissement.nom} » mis à jour.")
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    return redirect("plateforme")


@administrateur_plateforme_requis
def configuration_plateforme(request):
    configuration, _ = ConfigurationPlateforme.objects.get_or_create(pk=1)
    formulaire = FormulaireConfigurationPlateforme(
        request.POST or None,
        request.FILES or None,
        instance=configuration,
    )
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        messages.success(request, "L’identité de la plateforme a été mise à jour.")
        return redirect("configuration_plateforme")
    return render(request, "noyau/configuration_plateforme.html", {"formulaire": formulaire})
