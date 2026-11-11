"""Services métier de la structure académique."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Etablissement, ParametresEtablissement, TypeEtablissement
from applications.noyau.services import enregistrer_audit, vocabulaire

from .models import AnneeAcademique, Classe, Faculte, Niveau, Periode, PresetAcademique, Programme


def annee_active(etablissement):
    return AnneeAcademique.sans_filtre.filter(
        etablissement=etablissement, statut=AnneeAcademique.Statut.ACTIVE
    ).first()


def exiger_annee_active(etablissement):
    annee = annee_active(etablissement)
    if annee is None:
        raise ErreurMetier("Aucune année académique active : activez une année avant toute inscription.")
    return annee


def generer_periodes(annee, nombre, libelle):
    """Découpe l'année en ``nombre`` périodes consécutives de durée égale."""
    if nombre < 1:
        raise ErreurMetier("Une année doit comporter au moins une période.")
    total = (annee.date_fin - annee.date_debut).days + 1
    duree = total // nombre
    debut = annee.date_debut
    periodes = []
    for ordre in range(1, nombre + 1):
        fin = annee.date_fin if ordre == nombre else debut + timedelta(days=duree - 1)
        periodes.append(
            Periode.sans_filtre.create(
                etablissement=annee.etablissement, annee=annee, nom=f"{libelle} {ordre}",
                date_debut=debut, date_fin=fin, ordre=ordre,
            )
        )
        debut = fin + timedelta(days=1)
    return periodes


@transaction.atomic
def creer_annee(etablissement, designation, date_debut, date_fin, nombre_periodes=None, par=None):
    if date_fin <= date_debut:
        raise ErreurMetier("La date de fin doit être postérieure à la date de début.")
    if AnneeAcademique.sans_filtre.filter(etablissement=etablissement, designation=designation).exists():
        raise ErreurMetier(f"L'année « {designation} » existe déjà.")
    if nombre_periodes is None:
        parametres = ParametresEtablissement.objects.filter(etablissement=etablissement).first()
        nombre_periodes = (
            parametres.nombre_periodes_par_annee
            if parametres
            else 2 if etablissement.type == TypeEtablissement.UNIVERSITAIRE else 3
        )
    annee = AnneeAcademique.sans_filtre.create(
        etablissement=etablissement, designation=designation, date_debut=date_debut, date_fin=date_fin
    )
    generer_periodes(annee, nombre_periodes, vocabulaire(etablissement, "periode"))
    enregistrer_audit(etablissement, par, "annee.creation", annee, apres={"designation": designation})
    return annee


@transaction.atomic
def modifier_dates_annee(annee, date_debut, date_fin, par=None):
    if annee.statut == AnneeAcademique.Statut.CLOTUREE:
        raise ErreurMetier("Une année académique clôturée ne peut pas être modifiée.")
    if date_fin <= date_debut:
        raise ErreurMetier("La date de fin doit être postérieure à la date de début.")
    periodes = list(Periode.sans_filtre.filter(annee=annee).order_by("ordre"))
    periode_hors_annee = next(
        (
            periode for periode in periodes
            if periode.date_debut < date_debut or periode.date_fin > date_fin
        ),
        None,
    )
    if periode_hors_annee:
        raise ErreurMetier(
            f"Les nouvelles dates excluraient une partie de « {periode_hors_annee.nom} »."
        )
    avant = {"date_debut": annee.date_debut, "date_fin": annee.date_fin}
    annee.date_debut = date_debut
    annee.date_fin = date_fin
    annee.save(update_fields=["date_debut", "date_fin"])
    enregistrer_audit(
        annee.etablissement, par, "annee.modification_dates", annee,
        avant=avant, apres={"date_debut": date_debut, "date_fin": date_fin},
    )
    return annee


@transaction.atomic
def creer_periode(annee, nom, date_debut, date_fin, par=None):
    if annee.statut == AnneeAcademique.Statut.CLOTUREE:
        raise ErreurMetier("Impossible d'ajouter une période à une année clôturée.")
    _valider_dates_periode(annee, date_debut, date_fin)
    ordre = (Periode.sans_filtre.filter(annee=annee).aggregate(maximum=Max("ordre"))["maximum"] or 0) + 1
    periode = Periode.sans_filtre.create(
        etablissement=annee.etablissement, annee=annee, nom=nom.strip(),
        date_debut=date_debut, date_fin=date_fin, ordre=ordre,
    )
    enregistrer_audit(annee.etablissement, par, "periode.creation", periode, apres={"nom": periode.nom})
    return periode


def _valider_dates_periode(annee, date_debut, date_fin, periode_pk=None):
    if date_fin < date_debut:
        raise ErreurMetier("La date de fin doit être postérieure ou égale à la date de début.")
    if date_debut < annee.date_debut or date_fin > annee.date_fin:
        raise ErreurMetier("Les dates de la période doivent rester dans celles de l'année académique.")
    chevauchement = Periode.sans_filtre.filter(
        annee=annee, date_debut__lte=date_fin, date_fin__gte=date_debut
    ).exclude(pk=periode_pk).first()
    if chevauchement:
        raise ErreurMetier(f"Cette période chevauche « {chevauchement.nom} ».")


@transaction.atomic
def modifier_periode(periode, nom, date_debut, date_fin, par=None):
    if periode.annee.statut == AnneeAcademique.Statut.CLOTUREE:
        raise ErreurMetier("Une période appartenant à une année clôturée ne peut pas être modifiée.")
    _valider_dates_periode(periode.annee, date_debut, date_fin, periode.pk)
    avant = {"nom": periode.nom, "date_debut": periode.date_debut, "date_fin": periode.date_fin}
    periode.nom = nom.strip()
    periode.date_debut = date_debut
    periode.date_fin = date_fin
    periode.save(update_fields=["nom", "date_debut", "date_fin"])
    enregistrer_audit(
        periode.etablissement, par, "periode.modification", periode, avant=avant,
        apres={"nom": periode.nom, "date_debut": date_debut, "date_fin": date_fin},
    )
    return periode


def valider_periodes(annee):
    periodes = list(Periode.sans_filtre.filter(annee=annee).order_by("ordre"))
    if not periodes:
        raise ErreurMetier("L'année doit comporter au moins une période.")
    precedente = None
    for periode in periodes:
        if periode.date_debut < annee.date_debut or periode.date_fin > annee.date_fin:
            raise ErreurMetier(f"La période « {periode.nom} » dépasse les dates de l'année.")
        if precedente and periode.date_debut <= precedente.date_fin:
            raise ErreurMetier(f"Les périodes « {precedente.nom} » et « {periode.nom} » se chevauchent.")
        precedente = periode


@transaction.atomic
def activer_annee(annee, par=None):
    """Active l'année. Une seule année peut être active à la fois pour un établissement."""
    verrou = list(AnneeAcademique.sans_filtre.select_for_update().filter(etablissement=annee.etablissement))
    autre = next((a for a in verrou if a.statut == AnneeAcademique.Statut.ACTIVE and a.pk != annee.pk), None)
    if autre is not None:
        raise ErreurMetier(f"L'année « {autre} » est déjà active : clôturez-la avant d'en activer une autre.")
    annee.refresh_from_db()
    if annee.statut != AnneeAcademique.Statut.PREPARATION:
        raise ErreurMetier("Seule une année en préparation peut être activée.")
    valider_periodes(annee)
    annee.statut = AnneeAcademique.Statut.ACTIVE
    annee.save(update_fields=["statut"])
    enregistrer_audit(annee.etablissement, par, "annee.activation", annee)
    return annee


@transaction.atomic
def cloturer_annee(annee, par=None):
    if annee.statut != AnneeAcademique.Statut.ACTIVE:
        raise ErreurMetier("Seule l'année active peut être clôturée.")
    Periode.sans_filtre.filter(annee=annee).update(
        statut=Periode.Statut.CLOTUREE, saisie_ouverte=False
    )
    annee.statut = AnneeAcademique.Statut.CLOTUREE
    annee.save(update_fields=["statut"])
    enregistrer_audit(annee.etablissement, par, "annee.cloture", annee)
    return annee


@transaction.atomic
def ouvrir_periode(periode, par=None):
    if not periode.annee.est_active:
        raise ErreurMetier("Une période ne peut être ouverte que dans l'année active.")
    if periode.statut == Periode.Statut.CLOTUREE:
        raise ErreurMetier("Cette période est clôturée.")
    periode.statut = Periode.Statut.OUVERTE
    periode.saisie_ouverte = True
    periode.save(update_fields=["statut", "saisie_ouverte"])
    enregistrer_audit(periode.etablissement, par, "periode.ouverture", periode)
    return periode


@transaction.atomic
def fermer_periode(periode, par=None):
    periode.statut = Periode.Statut.CLOTUREE
    periode.saisie_ouverte = False
    periode.save(update_fields=["statut", "saisie_ouverte"])
    enregistrer_audit(periode.etablissement, par, "periode.cloture", periode)
    return periode


def basculer_saisie(periode, ouverte, par=None):
    if periode.statut != Periode.Statut.OUVERTE:
        raise ErreurMetier("La saisie ne peut être gérée que sur une période ouverte.")
    periode.saisie_ouverte = ouverte
    periode.save(update_fields=["saisie_ouverte"])
    enregistrer_audit(periode.etablissement, par, "periode.saisie", periode, apres={"saisie_ouverte": ouverte})
    return periode


def creer_faculte(etablissement, nom, code=""):
    if not etablissement.est_universitaire:
        raise ErreurMetier("Les facultés n'existent que dans un établissement universitaire.")
    return Faculte.sans_filtre.create(etablissement=etablissement, nom=nom, code=code)


def creer_programme(faculte, nom, code=""):
    return Programme.sans_filtre.create(etablissement=faculte.etablissement, faculte=faculte, nom=nom, code=code)


@transaction.atomic
def creer_niveau(etablissement, nom, programme=None, ordre=None):
    """École : niveau sans programme. Université : niveau obligatoirement rattaché à un programme."""
    if programme is None:
        Etablissement.objects.select_for_update().get(pk=etablissement.pk)
    else:
        Programme.sans_filtre.select_for_update().get(pk=programme.pk)
    if etablissement.est_universitaire and programme is None:
        raise ErreurMetier("Dans une université, un niveau doit être rattaché à un programme.")
    if not etablissement.est_universitaire and programme is not None:
        raise ErreurMetier("Un établissement scolaire n'a pas de programmes : le niveau est direct.")
    if programme is not None and programme.etablissement_id != etablissement.pk:
        raise ErreurMetier("Ce programme appartient à un autre établissement.")
    if Niveau.sans_filtre.filter(etablissement=etablissement, programme=programme, nom=nom).exists():
        raise ErreurMetier(f"Le niveau « {nom} » existe déjà.")
    if ordre is None:
        maximum = Niveau.sans_filtre.filter(etablissement=etablissement, programme=programme).aggregate(m=Max("ordre"))["m"]
        ordre = (maximum or 0) + 1
    return Niveau.sans_filtre.create(etablissement=etablissement, programme=programme, nom=nom, ordre=ordre)


def creer_classe(niveau, annee, nom, effectif_max=None, site=None):
    if niveau.etablissement.est_universitaire:
        raise ErreurMetier("Les classes concernent les écoles classiques, pas les universités.")
    if niveau.etablissement_id != annee.etablissement_id:
        raise ErreurMetier("Le niveau et l'année appartiennent à des établissements différents.")
    if site is not None and site.etablissement_id != niveau.etablissement_id:
        raise ErreurMetier("Le site et la classe doivent appartenir au même établissement.")
    if Classe.sans_filtre.filter(niveau=niveau, annee=annee, nom=nom).exists():
        raise ErreurMetier(f"La classe « {nom} » existe déjà pour ce niveau et cette année.")
    return Classe.sans_filtre.create(
        etablissement=niveau.etablissement, niveau=niveau, annee=annee, nom=nom,
        effectif_max=effectif_max, site=site,
    )


@transaction.atomic
def modifier_niveau(niveau, nom, par=None):
    niveau = Niveau.sans_filtre.select_for_update().get(pk=niveau.pk)
    ancien_nom = niveau.nom
    niveau.nom = nom.strip()
    try:
        niveau.save(update_fields=["nom"])
    except ValidationError as erreur:
        raise ErreurMetier("; ".join(erreur.messages)) from erreur
    enregistrer_audit(
        niveau.etablissement, par, "niveau.modification", niveau,
        avant={"nom": ancien_nom}, apres={"nom": niveau.nom},
    )
    return niveau


@transaction.atomic
def modifier_classe(classe, nom, par=None):
    classe = Classe.sans_filtre.select_for_update().get(pk=classe.pk)
    ancien_nom = classe.nom
    classe.nom = nom.strip()
    try:
        classe.save(update_fields=["nom"])
    except ValidationError as erreur:
        raise ErreurMetier("; ".join(erreur.messages)) from erreur
    enregistrer_audit(
        classe.etablissement, par, "classe.modification", classe,
        avant={"nom": ancien_nom}, apres={"nom": classe.nom},
    )
    return classe


@transaction.atomic
def dupliquer_annee(source, cible, par=None):
    """Reprend classes, barèmes et coefficients de l'année source dans l'année cible."""
    from applications.pedagogie.services import dupliquer_matieres_niveaux

    if source.etablissement_id != cible.etablissement_id:
        raise ErreurMetier("Les deux années doivent appartenir au même établissement.")
    copiees = 0
    for classe in Classe.sans_filtre.filter(annee=source):
        _, creee = Classe.sans_filtre.get_or_create(
            etablissement=classe.etablissement, niveau=classe.niveau, annee=cible, nom=classe.nom,
            defaults={"effectif_max": classe.effectif_max, "site": classe.site},
        )
        copiees += int(creee)
    matieres = dupliquer_matieres_niveaux(source, cible)
    enregistrer_audit(cible.etablissement, par, "annee.duplication", cible, apres={"classes": copiees, "matieres": matieres})
    return copiees, matieres


NIVEAUX_STANDARDS = [
    ("7e année fondamentale", "7e"), ("8e année fondamentale", "8e"), ("9e année fondamentale", "9e"),
    ("NS1", "NS1"), ("NS2", "NS2"), ("NS3", "NS3"), ("NS4 / Philosophie", "NS4"),
]


@transaction.atomic
def configuration_rapide(etablissement, designation, date_debut, date_fin, nombre_periodes,
                         niveaux_standards=True, classes_par_niveau=1, par=None):
    """Prépare un établissement en une seule opération : année active, périodes, niveaux et classes."""
    annee = creer_annee(etablissement, designation, date_debut, date_fin, nombre_periodes, par=par)
    activer_annee(annee, par=par)
    if niveaux_standards and not etablissement.est_universitaire:
        for nom, court in NIVEAUX_STANDARDS:
            niveau = Niveau.sans_filtre.filter(etablissement=etablissement, programme=None, nom=nom).first() \
                or creer_niveau(etablissement, nom)
            for lettre in "ABCDEFGH"[:max(0, classes_par_niveau)]:
                if not Classe.sans_filtre.filter(niveau=niveau, annee=annee, nom=f"{court} {lettre}").exists():
                    creer_classe(niveau, annee, f"{court} {lettre}")
    return annee


@transaction.atomic
def appliquer_preset(preset, par=None):
    """Crée les niveaux manquants d'un preset sans modifier les niveaux existants."""
    preset = PresetAcademique.sans_filtre.select_for_update().get(pk=preset.pk)
    if not preset.actif:
        raise ErreurMetier("Ce preset académique est désactivé.")
    if not isinstance(preset.niveaux, list) or not preset.niveaux:
        raise ErreurMetier("Le preset ne contient aucun niveau.")

    noms = []
    for valeur in preset.niveaux:
        if not isinstance(valeur, str) or not valeur.strip():
            raise ErreurMetier("Chaque niveau du preset doit avoir un nom.")
        nom = valeur.strip()
        if nom.casefold() in {deja.casefold() for deja in noms}:
            raise ErreurMetier(f"Le niveau « {nom} » apparaît plusieurs fois dans le preset.")
        noms.append(nom)

    creees = []
    for ordre, nom in enumerate(noms, start=1):
        niveau = Niveau.sans_filtre.filter(
            etablissement=preset.etablissement, programme=None, nom__iexact=nom
        ).first()
        if niveau is None:
            niveau = Niveau.sans_filtre.create(
                etablissement=preset.etablissement, nom=nom, ordre=ordre
            )
            creees.append(niveau)
    enregistrer_audit(
        preset.etablissement, par, "academique.preset_application", preset,
        apres={"niveaux_crees": [niveau.nom for niveau in creees]},
    )
    return creees
