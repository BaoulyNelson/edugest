"""Services métier des évaluations : configuration, saisie, calcul et publication."""
import hashlib
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.core.files.base import ContentFile
from django.utils import timezone

from applications.apprenants.models import Apprenant, Inscription, LienResponsable
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import ParametresEtablissement
from applications.noyau.services import enregistrer_audit, verifier_permission
from applications.pedagogie.services import bareme_applique, coefficient_applique, matiere_enseignee

from .models import (
    ComposanteEvaluation, ConfigurationEvaluation, DocumentResultat,
    HistoriqueNote, Note, ResultatPeriode,
)

DEUX_DECIMALES = Decimal("0.01")


def formater(valeur):
    """Affiche un nombre sans zéros inutiles (20.00 -> 20)."""
    if valeur is None:
        return "-"
    return format(Decimal(valeur).normalize(), "f")


def convertir_decimal(valeur):
    if valeur is None or valeur == "":
        return None
    try:
        return Decimal(str(valeur).replace(",", ".").strip())
    except InvalidOperation:
        raise ErreurMetier(f"Valeur numérique invalide : « {valeur} ».")


def seuil_reussite(etablissement):
    parametres = ParametresEtablissement.objects.filter(etablissement=etablissement).first()
    return parametres.seuil_reussite_pct if parametres else Decimal("50")


def revoquer_documents_resultat(inscription, periode, par, motif):
    documents = DocumentResultat.sans_filtre.filter(
        inscription=inscription, periode=periode, revoque_le__isnull=True
    )
    for document in documents:
        document.revoque_le = timezone.now()
        document.motif_revocation = motif
        document.save(update_fields=["revoque_le", "motif_revocation"])
        enregistrer_audit(
            document.etablissement, par, "resultat.document_revocation", document,
            motif=motif, apres={"version": document.version},
        )


def inscriptions_concernees(configuration):
    """Inscriptions validées concernées par l'évaluation (classe, ou niveau pour une université)."""
    affectation = configuration.affectation
    requete = Inscription.sans_filtre.filter(
        etablissement=configuration.etablissement, annee=configuration.periode.annee,
        statut=Inscription.Statut.VALIDEE, niveau=affectation.matiere_niveau.niveau,
    )
    if affectation.classe_id:
        requete = requete.filter(classe=affectation.classe)
    return requete.select_related("apprenant").order_by("apprenant__nom", "apprenant__prenoms")


@transaction.atomic
def creer_configuration(affectation, periode, par=None):
    if periode.annee_id != affectation.matiere_niveau.annee_id:
        raise ErreurMetier("La période n'appartient pas à l'année de cette matière.")
    if not matiere_enseignee(affectation.matiere_niveau, affectation.classe):
        raise ErreurMetier("Cette matière n'est pas enseignée dans cette classe.")
    configuration, _ = ConfigurationEvaluation.sans_filtre.get_or_create(
        affectation=affectation, periode=periode, defaults={"etablissement": affectation.etablissement}
    )
    return configuration


def bareme_de_configuration(configuration):
    affectation = configuration.affectation
    return bareme_applique(affectation.matiere_niveau, affectation.classe)


def somme_composantes(configuration):
    return sum((c.bareme for c in configuration.composantes.all()), Decimal("0"))


@transaction.atomic
def definir_composantes(configuration, composantes, par=None, confirmer_perte_notes=False):
    """Remplace les composantes d'un brouillon. ``composantes`` : liste de (intitulé, barème)."""
    configuration = ConfigurationEvaluation.sans_filtre.select_for_update().get(pk=configuration.pk)
    if configuration.statut != ConfigurationEvaluation.Statut.BROUILLON:
        raise ErreurMetier("La configuration est validée : rouvrez-la (avec un motif) avant de la modifier.")
    nettoyees = []
    for intitule, bareme in composantes:
        intitule = (intitule or "").strip()
        bareme = convertir_decimal(bareme)
        if not intitule:
            raise ErreurMetier("Chaque composante doit avoir un intitulé.")
        if bareme is None or bareme <= 0:
            raise ErreurMetier(f"Le barème de « {intitule} » doit être strictement positif.")
        nettoyees.append((intitule, bareme))
    if not nettoyees:
        raise ErreurMetier("Ajoutez au moins une composante d'évaluation.")
    notes_existantes = Note.sans_filtre.filter(composante__configuration=configuration).count()
    if notes_existantes and not confirmer_perte_notes:
        raise ErreurMetier(
            f"{notes_existantes} note(s) sont déjà saisies : confirmez leur suppression pour redéfinir les composantes."
        )
    if notes_existantes:
        enregistrer_audit(configuration.etablissement, par, "evaluation.suppression_notes", configuration,
                          avant={"notes_supprimees": notes_existantes})
    ComposanteEvaluation.sans_filtre.filter(configuration=configuration).delete()
    for ordre, (intitule, bareme) in enumerate(nettoyees, start=1):
        ComposanteEvaluation.sans_filtre.create(
            etablissement=configuration.etablissement, configuration=configuration,
            intitule=intitule, bareme=bareme, ordre=ordre,
        )
    return configuration


@transaction.atomic
def valider_configuration(configuration, par=None):
    """Valide la configuration si la somme des barèmes égale exactement le barème de la matière."""
    origine = configuration
    configuration = ConfigurationEvaluation.sans_filtre.select_for_update().get(pk=configuration.pk)
    if configuration.statut != ConfigurationEvaluation.Statut.BROUILLON:
        raise ErreurMetier("Cette configuration est déjà validée.")
    if not configuration.composantes.exists():
        raise ErreurMetier("Ajoutez au moins une composante d'évaluation.")
    total = somme_composantes(configuration)
    attendu = bareme_de_configuration(configuration)
    if total != attendu:
        ecart = abs(attendu - total)
        sens = "il manque" if total < attendu else "il y a en trop"
        raise ErreurMetier(
            f"La somme des barèmes des composantes ({formater(total)}) est différente du barème de la matière "
            f"({formater(attendu)}) : {sens} {formater(ecart)} point(s)."
        )
    configuration.statut = ConfigurationEvaluation.Statut.VALIDEE
    configuration.save(update_fields=["statut"])
    origine.statut = configuration.statut
    enregistrer_audit(configuration.etablissement, par, "evaluation.validation", configuration)
    return configuration


@transaction.atomic
def rouvrir_configuration(configuration, motif, par=None):
    """Rouvre une configuration validée (interdit si des résultats sont publiés). Tracé avec motif."""
    if not (motif or "").strip():
        raise ErreurMetier("Un motif est obligatoire pour rouvrir une configuration validée.")
    if configuration.statut == ConfigurationEvaluation.Statut.BROUILLON:
        raise ErreurMetier("Cette configuration est déjà en brouillon.")
    if resultats_de_configuration(configuration).filter(publie=True).exists():
        raise ErreurMetier("Des résultats sont publiés : dépubliez-les avant de rouvrir la configuration.")
    configuration.statut = ConfigurationEvaluation.Statut.BROUILLON
    configuration.save(update_fields=["statut"])
    enregistrer_audit(configuration.etablissement, par, "evaluation.reouverture", configuration, motif=motif)
    return configuration


def resultats_de_configuration(configuration):
    return ResultatPeriode.sans_filtre.filter(
        periode=configuration.periode, matiere_niveau=configuration.affectation.matiere_niveau,
        inscription__in=inscriptions_concernees(configuration),
    )


@transaction.atomic
def saisir_notes(configuration, saisies, auteur, motif=""):
    """Enregistre des notes. ``auteur`` est l'appartenance de l'enseignant affecté.

    ``saisies`` : liste de dictionnaires {inscription_id, composante_id, valeur, etat}.
    """
    configuration = ConfigurationEvaluation.sans_filtre.select_for_update().select_related(
        "periode", "affectation"
    ).get(pk=configuration.pk)
    if configuration.statut != ConfigurationEvaluation.Statut.VALIDEE:
        raise ErreurMetier("La configuration doit être validée avant la saisie des notes.")
    periode = configuration.periode
    if periode.statut != "OUVERTE" or not periode.saisie_ouverte:
        raise ErreurMetier("La saisie des notes est fermée pour cette période.")
    if configuration.affectation.appartenance_id != auteur.pk:
        raise ErreurMetier("Vous n'êtes pas affecté à cette matière pour cette classe.")

    composantes = {c.pk: c for c in configuration.composantes.all()}
    inscriptions = {i.pk: i for i in inscriptions_concernees(configuration)}
    publies = set(
        resultats_de_configuration(configuration).filter(publie=True).values_list("inscription_id", flat=True)
    )
    existantes = {
        (n.composante_id, n.inscription_id): n
        for n in Note.sans_filtre.filter(composante__configuration=configuration)
    }
    crees = modifiees = 0
    inscriptions_modifiees = set()
    for saisie in saisies:
        composante = composantes.get(saisie["composante_id"])
        inscription = inscriptions.get(saisie["inscription_id"])
        if composante is None or inscription is None:
            raise ErreurMetier("Saisie refusée : apprenant ou composante hors du périmètre de l'évaluation.")
        etat = saisie.get("etat") or Note.Etat.SAISIE
        valeur = convertir_decimal(saisie.get("valeur"))
        if etat == Note.Etat.SAISIE and valeur is None:
            etat = Note.Etat.NON_RENSEIGNEE
        if etat == Note.Etat.SAISIE:
            if valeur < 0 or valeur > composante.bareme:
                raise ErreurMetier(
                    f"La note de {inscription.apprenant} pour « {composante.intitule} » doit être comprise "
                    f"entre 0 et {formater(composante.bareme)}."
                )
        else:
            valeur = None
        courante = existantes.get((composante.pk, inscription.pk))
        if courante is None:
            if etat == Note.Etat.NON_RENSEIGNEE:
                continue
            courante = Note.sans_filtre.create(
                etablissement=configuration.etablissement, composante=composante,
                inscription=inscription, valeur=valeur, etat=etat,
            )
            HistoriqueNote.sans_filtre.create(
                etablissement=configuration.etablissement, note=courante, inscription=inscription,
                composante=composante, nouvelle_valeur=valeur, nouvel_etat=etat,
                auteur=getattr(auteur, "utilisateur", None), motif=motif.strip(),
            )
            inscriptions_modifiees.add(inscription.pk)
            crees += 1
            continue
        if courante.valeur == valeur and courante.etat == etat:
            continue
        if inscription.pk in publies and not (motif or "").strip():
            raise ErreurMetier("Le résultat est publié : un motif est obligatoire pour modifier une note.")
        avant = {"valeur": courante.valeur, "etat": courante.etat}
        HistoriqueNote.sans_filtre.create(
            etablissement=configuration.etablissement, note=courante, inscription=inscription,
            composante=composante, ancienne_valeur=courante.valeur, ancien_etat=courante.etat,
            nouvelle_valeur=valeur, nouvel_etat=etat,
            auteur=getattr(auteur, "utilisateur", None), motif=motif.strip(),
        )
        inscriptions_modifiees.add(inscription.pk)
        courante.valeur, courante.etat = valeur, etat
        courante.save(update_fields=["valeur", "etat"])
        modifiees += 1
        enregistrer_audit(
            configuration.etablissement, auteur.utilisateur, "note.modification", courante,
            avant=avant, apres={"valeur": valeur, "etat": etat}, motif=motif,
        )
    for inscription_id in inscriptions_modifiees.intersection(publies):
        inscription = inscriptions[inscription_id]
        revoquer_documents_resultat(
            inscription, periode, auteur.utilisateur, "Une note publiée a été modifiée."
        )
    calculer_resultats(configuration)
    return crees, modifiees


def _calculer(composantes, notes, seuil):
    total = Decimal("0")
    bareme_pris = Decimal("0")
    incomplet = False
    for composante in composantes:
        note = notes.get(composante.pk)
        etat = note.etat if note else Note.Etat.NON_RENSEIGNEE
        if etat == Note.Etat.SAISIE:
            total += note.valeur
            bareme_pris += composante.bareme
        elif etat == Note.Etat.DISPENSE:
            continue
        else:
            incomplet = True
    if incomplet:
        return total, bareme_pris, None, ResultatPeriode.Statut.INCOMPLET
    if bareme_pris == 0:
        return total, bareme_pris, None, ResultatPeriode.Statut.DISPENSE
    pourcentage = (total / bareme_pris * 100).quantize(DEUX_DECIMALES)
    statut = ResultatPeriode.Statut.REUSSI if pourcentage >= seuil else ResultatPeriode.Statut.ECHEC
    return total, bareme_pris, pourcentage, statut


@transaction.atomic
def calculer_resultats(configuration):
    """Recalcule les résultats de la période. Une note absente n'est jamais comptée comme zéro."""
    composantes = list(configuration.composantes.all())
    seuil = seuil_reussite(configuration.etablissement)
    notes = {}
    for note in Note.sans_filtre.filter(composante__configuration=configuration):
        notes.setdefault(note.inscription_id, {})[note.composante_id] = note
    matiere_niveau = configuration.affectation.matiere_niveau
    resultats = []
    for inscription in inscriptions_concernees(configuration):
        total, bareme_pris, pourcentage, statut = _calculer(composantes, notes.get(inscription.pk, {}), seuil)
        resultat, _ = ResultatPeriode.sans_filtre.update_or_create(
            inscription=inscription, matiere_niveau=matiere_niveau, periode=configuration.periode,
            defaults={
                "etablissement": configuration.etablissement, "total": total,
                "bareme_applique": bareme_pris, "pourcentage": pourcentage, "statut": statut,
            },
        )
        resultats.append(resultat)
    return resultats


@transaction.atomic
def publier_resultats(configuration, par, forcer=False):
    """Publie les résultats complets. Refuse s'il reste des résultats incomplets (sauf ``forcer``)."""
    if configuration.statut == ConfigurationEvaluation.Statut.BROUILLON:
        raise ErreurMetier("Validez la configuration avant de publier les résultats.")
    resultats = calculer_resultats(configuration)
    incomplets = [r for r in resultats if r.statut == ResultatPeriode.Statut.INCOMPLET]
    if incomplets and not forcer:
        raise ErreurMetier(
            f"{len(incomplets)} résultat(s) sont incomplets (note absente ou non renseignée) : "
            "complétez la saisie avant de publier."
        )
    publiables = [r.pk for r in resultats if r.statut != ResultatPeriode.Statut.INCOMPLET]
    ResultatPeriode.sans_filtre.filter(pk__in=publiables).update(publie=True, date_publication=timezone.now())
    enregistrer_audit(configuration.etablissement, par, "resultats.publication", configuration,
                      apres={"publies": len(publiables), "incomplets": len(incomplets)})
    return len(publiables), len(incomplets)


@transaction.atomic
def depublier_resultats(configuration, par, motif):
    if not (motif or "").strip():
        raise ErreurMetier("Un motif est obligatoire pour dépublier des résultats.")
    resultat_requete = resultats_de_configuration(configuration)
    inscriptions = list(resultat_requete.values_list("inscription", flat=True).distinct())
    nombre = resultat_requete.update(publie=False, date_publication=None)
    for inscription in Inscription.sans_filtre.filter(pk__in=inscriptions):
        revoquer_documents_resultat(
            inscription, configuration.periode, par, f"Résultats dépubliés : {motif.strip()}"
        )
    enregistrer_audit(configuration.etablissement, par, "resultats.depublication", configuration,
                      apres={"resultats": nombre}, motif=motif)
    return nombre


@transaction.atomic
def verrouiller_configuration(configuration, par=None):
    if configuration.statut != ConfigurationEvaluation.Statut.VALIDEE:
        raise ErreurMetier("Seule une configuration validée peut être verrouillée.")
    configuration.statut = ConfigurationEvaluation.Statut.VERROUILLEE
    configuration.save(update_fields=["statut"])
    enregistrer_audit(configuration.etablissement, par, "evaluation.verrouillage", configuration)
    return configuration


def moyenne_generale(inscription, periode, seulement_publies=False):
    """Moyenne pondérée normalisée (pourcentages x coefficients), exprimée dans l'échelle de l'établissement."""
    requete = ResultatPeriode.sans_filtre.filter(
        inscription=inscription, periode=periode,
        statut__in=[ResultatPeriode.Statut.REUSSI, ResultatPeriode.Statut.ECHEC],
    ).select_related("matiere_niveau")
    if seulement_publies:
        requete = requete.filter(publie=True)
    somme = poids = Decimal("0")
    total_points = bareme_total = Decimal("0")
    comptees = 0
    for resultat in requete:
        coefficient = coefficient_applique(resultat.matiere_niveau, inscription.classe)
        somme += resultat.pourcentage * coefficient
        poids += coefficient
        total_points += resultat.total
        bareme_total += resultat.bareme_applique
        comptees += 1
    if poids == 0:
        return None
    pourcentage = (somme / poids).quantize(DEUX_DECIMALES)
    parametres = ParametresEtablissement.objects.filter(etablissement=inscription.etablissement).first()
    echelle = parametres.echelle_moyenne if parametres else 20
    return {
        "pourcentage": pourcentage,
        "moyenne": (pourcentage * echelle / 100).quantize(DEUX_DECIMALES),
        "echelle": echelle,
        "matieres_comptees": comptees,
        "total_points": total_points,
        "bareme_total": bareme_total,
    }


def rangs_par_resultat(resultats):
    """Classe les résultats publiés par matière, période et classe, en conservant les ex æquo."""
    resultats = list(resultats)
    if not resultats:
        return {}
    periodes = {resultat.periode_id for resultat in resultats}
    matieres = {resultat.matiere_niveau_id for resultat in resultats}
    notes_par_groupe = {}
    lignes = ResultatPeriode.objects.filter(
        etablissement_id=resultats[0].etablissement_id,
        periode_id__in=periodes,
        matiere_niveau_id__in=matieres,
        publie=True,
        pourcentage__isnull=False,
    ).values_list(
        "pk", "periode_id", "matiere_niveau_id", "inscription__classe_id", "pourcentage"
    )
    groupes_par_id = {}
    for pk, periode_id, matiere_id, classe_id, pourcentage in lignes:
        cle = (periode_id, matiere_id, classe_id)
        groupes_par_id[pk] = (cle, pourcentage)
        notes_par_groupe.setdefault(cle, []).append(pourcentage)
    rangs = {}
    for resultat in resultats:
        ligne = groupes_par_id.get(resultat.pk)
        if not resultat.publie or resultat.pourcentage is None or ligne is None:
            rangs[resultat.pk] = None
            continue
        cle, pourcentage = ligne
        rangs[resultat.pk] = 1 + sum(note > pourcentage for note in notes_par_groupe[cle])
    return rangs


def bulletins_synthetiques(periode, filtres=None):
    """Construit un bulletin consolidé uniquement à partir des résultats publiés."""
    from applications.pedagogie.models import DerogationClasse, MatiereNiveau

    filtres = filtres or {}
    inscriptions = Inscription.objects.filter(
        annee_id=periode.annee_id, statut=Inscription.Statut.VALIDEE
    ).select_related("apprenant", "classe", "niveau")
    if filtres.get("niveau"):
        inscriptions = inscriptions.filter(niveau_id=filtres["niveau"])
    if filtres.get("classe"):
        inscriptions = inscriptions.filter(classe_id=filtres["classe"])
    if filtres.get("apprenant"):
        terme = filtres["apprenant"]
        inscriptions = inscriptions.filter(
            Q(apprenant__nom__icontains=terme)
            | Q(apprenant__prenoms__icontains=terme)
            | Q(apprenant__matricule__icontains=terme)
        )
    inscriptions = list(inscriptions.order_by("apprenant__nom", "apprenant__prenoms"))
    if not inscriptions:
        return []

    niveaux = {inscription.niveau_id for inscription in inscriptions}
    matieres_par_niveau = {}
    for matiere_niveau in MatiereNiveau.objects.filter(
        annee_id=periode.annee_id, niveau_id__in=niveaux
    ).select_related("matiere"):
        matieres_par_niveau.setdefault(matiere_niveau.niveau_id, []).append(matiere_niveau)
    derogations_exclues = set(DerogationClasse.objects.filter(
        classe_id__in={inscription.classe_id for inscription in inscriptions if inscription.classe_id},
        matiere_niveau_id__in={matiere.pk for liste in matieres_par_niveau.values() for matiere in liste},
        exclue=True,
    ).values_list("classe_id", "matiere_niveau_id"))
    resultats_par_inscription = {}
    for resultat in ResultatPeriode.objects.filter(
        periode=periode, inscription__in=inscriptions, publie=True
    ).select_related("matiere_niveau"):
        resultats_par_inscription.setdefault(resultat.inscription_id, {})[
            resultat.matiere_niveau_id
        ] = resultat

    bulletins = []
    for inscription in inscriptions:
        matieres_attendues = [
            matiere for matiere in matieres_par_niveau.get(inscription.niveau_id, [])
            if (inscription.classe_id, matiere.pk) not in derogations_exclues
        ]
        resultats = resultats_par_inscription.get(inscription.pk, {})
        complets = bool(matieres_attendues) and all(
            (resultat := resultats.get(matiere.pk)) is not None
            and resultat.statut != ResultatPeriode.Statut.INCOMPLET
            for matiere in matieres_attendues
        )
        moyenne = moyenne_generale(inscription, periode, seulement_publies=True)
        bulletins.append({
            "inscription": inscription,
            "moyenne": moyenne,
            "matieres_comptees": moyenne["matieres_comptees"] if moyenne else 0,
            "matieres_attendues": len(matieres_attendues),
            "matieres_bulletin": [matiere.matiere for matiere in matieres_attendues],
            "baremes_par_matiere": {
                matiere.matiere_id: bareme_applique(matiere, inscription.classe)
                for matiere in matieres_attendues
            },
            "resultats_par_matiere": {
                matiere.matiere_id: resultats.get(matiere.pk)
                for matiere in matieres_attendues
            },
            "complet": complets,
            "rang": None,
        })

    groupes = {}
    for bulletin in bulletins:
        inscription = bulletin["inscription"]
        cle = inscription.classe_id or ("niveau", inscription.niveau_id)
        if bulletin["complet"] and bulletin["moyenne"]:
            groupes.setdefault(cle, []).append(bulletin)
    for groupe in groupes.values():
        scores = [bulletin["moyenne"]["pourcentage"] for bulletin in groupe]
        for bulletin in groupe:
            score = bulletin["moyenne"]["pourcentage"]
            bulletin["rang"] = 1 + sum(autre > score for autre in scores)
    return bulletins


def statistiques_configuration(configuration):
    """Indicateurs de classe : effectif, moyenne, taux de réussite, apprenants en difficulté, classement."""
    resultats = list(resultats_de_configuration(configuration).select_related("inscription__apprenant"))
    complets = [r for r in resultats if r.pourcentage is not None]
    reussis = [r for r in complets if r.statut == ResultatPeriode.Statut.REUSSI]
    en_difficulte = sorted(
        (r for r in complets if r.statut == ResultatPeriode.Statut.ECHEC), key=lambda r: r.pourcentage
    )
    moyenne = None
    if complets:
        moyenne = (sum(r.pourcentage for r in complets) / len(complets)).quantize(DEUX_DECIMALES)
    parametres = ParametresEtablissement.objects.filter(etablissement=configuration.etablissement).first()
    classement = []
    if parametres and parametres.classement_autorise:
        classement = sorted(complets, key=lambda r: r.pourcentage, reverse=True)
    return {
        "effectif": len(resultats),
        "complets": len(complets),
        "incomplets": len(resultats) - len(complets),
        "moyenne_pct": moyenne,
        "taux_reussite": (Decimal(len(reussis)) / len(complets) * 100).quantize(DEUX_DECIMALES) if complets else None,
        "en_difficulte": en_difficulte,
        "classement": classement,
    }


def affectations_visibles(appartenance):
    from applications.pedagogie.models import AffectationEnseignant

    requete = AffectationEnseignant.objects.select_related(
        "matiere_niveau__matiere", "matiere_niveau__niveau", "classe", "appartenance__utilisateur"
    )
    if verifier_permission(appartenance.utilisateur, appartenance, "resultats.consulter_tous"):
        return requete
    return requete.filter(appartenance=appartenance)


def resultats_visibles(utilisateur, appartenance, filtres=None):
    """Résultats consultables : tous (direction), ceux de ses affectations (enseignant), sinon rien."""
    requete = ResultatPeriode.objects.select_related(
        "inscription__apprenant", "inscription__classe", "inscription__niveau",
        "matiere_niveau__matiere", "periode__annee",
    )
    if verifier_permission(utilisateur, appartenance, "resultats.consulter_tous"):
        pass
    elif verifier_permission(utilisateur, appartenance, "resultats.consulter"):
        condition = Q(pk__in=[])
        for affectation in appartenance.affectations.all():
            critere = Q(matiere_niveau=affectation.matiere_niveau)
            if affectation.classe_id:
                critere &= Q(inscription__classe=affectation.classe)
            condition |= critere
        requete = requete.filter(condition)
    else:
        return requete.none()
    filtres = filtres or {}
    if filtres.get("annee"):
        requete = requete.filter(periode__annee_id=filtres["annee"])
    if filtres.get("periode"):
        requete = requete.filter(periode_id=filtres["periode"])
    if filtres.get("niveau"):
        requete = requete.filter(inscription__niveau_id=filtres["niveau"])
    if filtres.get("classe"):
        requete = requete.filter(inscription__classe_id=filtres["classe"])
    if filtres.get("matiere"):
        requete = requete.filter(matiere_niveau__matiere_id=filtres["matiere"])
    if filtres.get("composante"):
        configurations = ConfigurationEvaluation.sans_filtre.filter(
            etablissement_id=OuterRef("etablissement_id"),
            periode_id=OuterRef("periode_id"),
            affectation__matiere_niveau_id=OuterRef("matiere_niveau_id"),
            composantes__pk=filtres["composante"],
        ).filter(
            Q(affectation__classe__isnull=True)
            | Q(affectation__classe_id=OuterRef("inscription__classe_id"))
        )
        requete = requete.annotate(_a_composante=Exists(configurations)).filter(_a_composante=True)
    if filtres.get("statut"):
        requete = requete.filter(statut=filtres["statut"])
    if filtres.get("publie") in ("1", "0"):
        requete = requete.filter(publie=filtres["publie"] == "1")
    if filtres.get("apprenant"):
        terme = filtres["apprenant"]
        requete = requete.filter(
            Q(inscription__apprenant__nom__icontains=terme)
            | Q(inscription__apprenant__prenoms__icontains=terme)
            | Q(inscription__apprenant__matricule__icontains=terme)
        )
    return requete.order_by("periode__annee", "periode__ordre", "inscription__apprenant__nom")


def resultats_portail(utilisateur):
    """Résultats publiés de l'apprenant connecté ou de ses enfants (responsable légal)."""
    identifiants = set(Apprenant.sans_filtre.filter(utilisateur=utilisateur).values_list("pk", flat=True))
    identifiants |= set(
        LienResponsable.sans_filtre.filter(responsable__utilisateur=utilisateur).values_list("apprenant_id", flat=True)
    )
    return ResultatPeriode.objects.filter(
        publie=True, inscription__apprenant_id__in=identifiants
    ).select_related("inscription__apprenant", "matiere_niveau__matiere", "periode__annee").order_by(
        "inscription__apprenant__nom", "periode__ordre", "matiere_niveau__matiere__nom"
    )


@transaction.atomic
def generer_document_resultat(inscription, periode, par):
    if inscription.etablissement_id != periode.etablissement_id or inscription.annee_id != periode.annee_id:
        raise ErreurMetier("L'inscription et la période ne correspondent pas au même établissement et à la même année.")
    resultats = list(ResultatPeriode.sans_filtre.filter(
        inscription=inscription, periode=periode
    ).select_related("matiere_niveau__matiere").order_by("matiere_niveau__matiere__nom"))
    if not resultats or any(not resultat.publie for resultat in resultats):
        raise ErreurMetier("Publiez tous les résultats de la période avant d'émettre le document.")

    snapshot = {
        "apprenant": str(inscription.apprenant),
        "matricule": inscription.apprenant.matricule,
        "annee": periode.annee.designation,
        "periode": periode.nom,
        "resultats": [
            {
                "matiere": resultat.matiere_niveau.matiere.nom,
                "total": str(resultat.total),
                "bareme": str(resultat.bareme_applique),
                "pourcentage": str(resultat.pourcentage) if resultat.pourcentage is not None else None,
                "statut": resultat.get_statut_display(),
            }
            for resultat in resultats
        ],
    }
    moyenne = moyenne_generale(inscription, periode, seulement_publies=True)
    if moyenne is not None:
        snapshot["moyenne"] = f'{moyenne["moyenne"]}/{moyenne["echelle"]}'

    lignes = [
        [r["matiere"], f'{r["total"]}/{r["bareme"]}', r["pourcentage"] or "—", r["statut"]]
        for r in snapshot["resultats"]
    ]
    if moyenne is not None:
        lignes.append(["Moyenne générale", snapshot["moyenne"], "", ""])
    from .exports import exporter_pdf

    contenu = exporter_pdf(
        f"Résultats · {inscription.apprenant} · {periode}",
        ["Matière", "Total", "Pourcentage", "Statut"], lignes,
    )
    dernier = DocumentResultat.sans_filtre.select_for_update().filter(
        inscription=inscription, periode=periode
    ).order_by("-version").first()
    version = dernier.version + 1 if dernier else 1
    document = DocumentResultat(
        etablissement=inscription.etablissement, inscription=inscription, periode=periode,
        version=version, empreinte_sha256=hashlib.sha256(contenu).hexdigest(),
        instantane=snapshot, cree_par=par,
    )
    document.fichier.save(
        f"resultats-v{version}.pdf", ContentFile(contenu), save=False
    )
    document.save()
    enregistrer_audit(
        inscription.etablissement, par, "resultat.document_creation", document,
        apres={"version": version, "empreinte_sha256": document.empreinte_sha256},
    )
    return document


@transaction.atomic
def revoquer_document_resultat(document, motif, par):
    document = DocumentResultat.sans_filtre.select_for_update().get(pk=document.pk)
    motif = (motif or "").strip()
    if not motif:
        raise ErreurMetier("Un motif est obligatoire pour révoquer un document.")
    if document.revoque_le:
        raise ErreurMetier("Ce document est déjà révoqué.")
    document.revoque_le = timezone.now()
    document.motif_revocation = motif
    document.save(update_fields=["revoque_le", "motif_revocation"])
    enregistrer_audit(
        document.etablissement, par, "resultat.document_revocation", document,
        motif=motif, apres={"version": document.version},
    )
    return document
