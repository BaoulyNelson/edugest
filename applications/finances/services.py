"""Services d'enregistrement et de synthèse des opérations financières."""
import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from applications.academique.models import AnneeAcademique
from applications.apprenants.models import Apprenant, Inscription, LienResponsable
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit, servir_numero

from .models import (
    AffectationPaiement, Depense, Echeance, Facture, GrilleFrais, LigneFacture,
    Paiement, Remboursement, TypeFrais,
)

CENTIMES = Decimal("0.01")


def _ajouter_mois(jour, mois):
    index = jour.month - 1 + mois
    annee, numero_mois = jour.year + index // 12, index % 12 + 1
    return date(annee, numero_mois, min(jour.day, calendar.monthrange(annee, numero_mois)[1]))


@transaction.atomic
def creer_type_frais(etablissement, nom, par=None):
    nom = nom.strip()
    if not nom:
        raise ErreurMetier("Le nom du type de frais est obligatoire.")
    if TypeFrais.sans_filtre.filter(etablissement=etablissement, nom__iexact=nom).exists():
        raise ErreurMetier("Ce type de frais existe déjà.")
    type_frais = TypeFrais.sans_filtre.create(etablissement=etablissement, nom=nom)
    enregistrer_audit(etablissement, par, "finance.type_frais.creation", type_frais)
    return type_frais


@transaction.atomic
def creer_grille_frais(etablissement, annee, niveau, type_frais, montant, nombre_echeances, premiere_echeance, par=None):
    if any(obj.etablissement_id != etablissement.pk for obj in (annee, niveau, type_frais)):
        raise ErreurMetier("La grille ne peut utiliser que des données du même établissement.")
    if not type_frais.actif:
        raise ErreurMetier("Un type de frais inactif ne peut pas être ajouté à une grille.")
    if annee.statut == AnneeAcademique.Statut.CLOTUREE:
        raise ErreurMetier("Une année clôturée ne peut pas recevoir de grille de frais.")
    if montant <= 0 or not 1 <= nombre_echeances <= 12:
        raise ErreurMetier("Le montant doit être positif et le nombre d'échéances compris entre 1 et 12.")
    if premiere_echeance < annee.date_debut or premiere_echeance > annee.date_fin:
        raise ErreurMetier("La première échéance doit être comprise dans l'année académique.")
    if GrilleFrais.sans_filtre.filter(annee=annee, niveau=niveau, type_frais=type_frais).exists():
        raise ErreurMetier("Une grille existe déjà pour ce niveau et ce type de frais.")
    grille = GrilleFrais.sans_filtre.create(
        etablissement=etablissement, annee=annee, niveau=niveau, type_frais=type_frais,
        montant=montant, nombre_echeances=nombre_echeances, premiere_echeance=premiere_echeance,
    )
    enregistrer_audit(etablissement, par, "finance.grille.creation", grille, apres={"montant": str(montant)})
    return grille


@transaction.atomic
def generer_facture(inscription, par=None):
    if inscription.statut != Inscription.Statut.VALIDEE:
        raise ErreurMetier("Une facture ne peut être émise que pour une inscription validée.")
    if any(
        objet.etablissement_id != inscription.etablissement_id
        for objet in (inscription.annee, inscription.niveau, inscription.apprenant)
    ):
        raise ErreurMetier("Les données de l'inscription ne correspondent pas au même établissement.")
    existante = Facture.sans_filtre.filter(inscription=inscription).first()
    if existante:
        return existante
    grilles = list(GrilleFrais.sans_filtre.filter(
        etablissement=inscription.etablissement, annee=inscription.annee,
        niveau=inscription.niveau, type_frais__actif=True,
    ).select_related("type_frais"))
    if not grilles:
        return None
    numero_sequence = servir_numero(inscription.etablissement, f"facture-{inscription.annee_id}")
    annee_numero = inscription.annee.date_debut.year
    facture = Facture.sans_filtre.create(
        etablissement=inscription.etablissement, inscription=inscription,
        numero=f"FAC-{annee_numero}-{numero_sequence:05d}",
        devise=inscription.etablissement.devise,
    )
    total = Decimal("0")
    for grille in grilles:
        LigneFacture.sans_filtre.create(
            etablissement=inscription.etablissement, facture=facture,
            libelle=grille.type_frais.nom, montant=grille.montant,
        )
        total += grille.montant
        part = (grille.montant / grille.nombre_echeances).quantize(CENTIMES)
        for ordre in range(1, grille.nombre_echeances + 1):
            montant_echeance = (
                grille.montant - part * (grille.nombre_echeances - 1)
                if ordre == grille.nombre_echeances else part
            )
            libelle = grille.type_frais.nom
            if grille.nombre_echeances > 1:
                libelle = f"{libelle} ({ordre}/{grille.nombre_echeances})"
            Echeance.sans_filtre.create(
                etablissement=inscription.etablissement, facture=facture, ordre=ordre,
                libelle=libelle, montant=montant_echeance,
                date_limite=_ajouter_mois(grille.premiere_echeance, ordre - 1),
            )
    facture.total = total
    facture.save(update_fields=["total"])
    enregistrer_audit(
        inscription.etablissement, par, "finance.facture.emission", facture,
        apres={"total": str(total), "devise": facture.devise},
    )
    return facture


@transaction.atomic
def enregistrer_paiement(etablissement, apprenant, montant, date_paiement, motif, mode, par, reference=""):
    if apprenant.etablissement_id != etablissement.pk or not apprenant.actif:
        raise ErreurMetier("L'apprenant est invalide pour cet établissement.")
    if montant <= 0:
        raise ErreurMetier("Le montant du paiement doit être supérieur à zéro.")
    paiement = Paiement.sans_filtre.create(
        etablissement=etablissement, apprenant=apprenant, montant=montant,
        date_paiement=date_paiement, motif=motif.strip(), mode=mode, enregistre_par=par,
        recu_par=par, reference=reference.strip(),
        numero_recu=f"REC-{timezone.localdate().year}-{servir_numero(etablissement, f'recu-{timezone.localdate().year}'):06d}",
    )
    enregistrer_audit(
        etablissement, par, "finance.paiement.enregistrement", paiement,
        apres={"montant": str(paiement.montant), "apprenant": str(apprenant)},
    )
    return paiement


def total_paye(facture):
    total_encaisse = facture.paiements.aggregate(total=Sum("montant"))["total"] or Decimal("0")
    total_rembourse = Remboursement.objects.filter(paiement__facture=facture).aggregate(
        total=Sum("montant")
    )["total"] or Decimal("0")
    return total_encaisse - total_rembourse


def solde_facture(facture):
    return max(Decimal("0"), facture.total - total_paye(facture))


def repartition_echeances(facture, aujourdhui=None):
    aujourdhui = aujourdhui or timezone.localdate()
    reste_a_imputer = total_paye(facture)
    resultat = []
    for echeance in facture.echeances.all():
        paye = min(reste_a_imputer, echeance.montant)
        reste_a_imputer -= paye
        reste = echeance.montant - paye
        resultat.append({
            "echeance": echeance, "paye": paye, "reste": reste,
            "en_retard": reste > 0 and echeance.date_limite < aujourdhui,
        })
    return resultat


def montant_exigible(facture, aujourdhui=None):
    return sum(
        (ligne["reste"] for ligne in repartition_echeances(facture, aujourdhui) if ligne["en_retard"]),
        Decimal("0"),
    )


@transaction.atomic
def encaisser_facture(facture, montant, mode, reference="", par=None):
    facture = Facture.sans_filtre.select_for_update().get(pk=facture.pk)
    montant = Decimal(montant).quantize(CENTIMES)
    if mode not in dict(Paiement.Mode.choices):
        raise ErreurMetier("Mode de paiement invalide.")
    if facture.statut == Facture.Statut.ANNULEE:
        raise ErreurMetier("Cette facture est annulée.")
    reste = solde_facture(facture)
    if montant <= 0 or montant > reste:
        raise ErreurMetier(f"Le montant doit être positif et ne pas dépasser le solde de {reste:.2f} {facture.devise}.")
    repartition_avant = repartition_echeances(facture)
    sequence = servir_numero(facture.etablissement, f"recu-{timezone.localdate().year}")
    paiement = Paiement.sans_filtre.create(
        etablissement=facture.etablissement, apprenant=facture.inscription.apprenant,
        facture=facture, montant=montant, date_paiement=timezone.localdate(),
        motif=f"Paiement de la facture {facture.numero}", mode=mode, reference=reference.strip(),
        enregistre_par=par, recu_par=par,
        numero_recu=f"REC-{timezone.localdate().year}-{sequence:06d}",
    )
    a_imputer = montant
    for ligne in repartition_avant:
        impute = min(a_imputer, ligne["reste"])
        if impute > 0:
            AffectationPaiement.sans_filtre.create(
                etablissement=facture.etablissement, paiement=paiement,
                echeance=ligne["echeance"], montant=impute,
            )
            a_imputer -= impute
        if not a_imputer:
            break
    total = total_paye(facture)
    facture.statut = (
        Facture.Statut.SOLDEE if total >= facture.total
        else Facture.Statut.PARTIELLE if total > 0
        else Facture.Statut.EMISE
    )
    facture.save(update_fields=["statut"])
    enregistrer_audit(
        facture.etablissement, par, "finance.facture.paiement", paiement,
        apres={"facture": facture.numero, "montant": str(montant), "mode": mode},
    )
    return paiement


@transaction.atomic
def enregistrer_remboursement(paiement, montant, motif, par=None):
    """Enregistre un remboursement partiel ou total sans dépasser l'encaissement initial."""
    paiement = Paiement.sans_filtre.select_for_update().get(pk=paiement.pk)
    montant = Decimal(montant).quantize(CENTIMES)
    motif = (motif or "").strip()
    deja_rembourse = paiement.remboursements.aggregate(total=Sum("montant"))["total"] or Decimal("0")
    disponible = paiement.montant - deja_rembourse
    if montant <= 0 or montant > disponible:
        raise ErreurMetier(
            f"Le remboursement doit être positif et ne pas dépasser le montant restant de "
            f"{disponible:.2f}."
        )
    if not motif:
        raise ErreurMetier("Le motif du remboursement est obligatoire.")
    remboursement = Remboursement.sans_filtre.create(
        etablissement=paiement.etablissement, paiement=paiement,
        montant=montant, motif=motif, effectue_par=par,
    )
    if paiement.facture_id:
        facture = Facture.sans_filtre.select_for_update().get(pk=paiement.facture_id)
        total = total_paye(facture)
        facture.statut = (
            Facture.Statut.SOLDEE if total >= facture.total
            else Facture.Statut.PARTIELLE if total > 0
            else Facture.Statut.EMISE
        )
        facture.save(update_fields=["statut"])
    enregistrer_audit(
        paiement.etablissement, par, "finance.paiement.remboursement", remboursement,
        apres={"paiement": paiement.pk, "montant": str(montant)}, motif=motif,
    )
    return remboursement


@transaction.atomic
def annuler_facture(facture, motif, par=None):
    facture = Facture.sans_filtre.select_for_update().get(pk=facture.pk)
    if facture.statut == Facture.Statut.ANNULEE:
        raise ErreurMetier("Cette facture est déjà annulée.")
    if facture.paiements.exists():
        raise ErreurMetier("Une facture déjà payée ne peut pas être annulée.")
    if not motif.strip():
        raise ErreurMetier("Le motif d'annulation est obligatoire.")
    facture.statut = Facture.Statut.ANNULEE
    facture.save(update_fields=["statut"])
    enregistrer_audit(facture.etablissement, par, "finance.facture.annulation", facture, motif=motif)
    return facture


def factures_accessibles(utilisateur, etablissement):
    apprenants = Apprenant.sans_filtre.filter(
        etablissement=etablissement
    ).filter(
        Q(utilisateur=utilisateur) | Q(liens_responsables__responsable__utilisateur=utilisateur)
    ).values("pk")
    return Facture.objects.filter(inscription__apprenant_id__in=apprenants).select_related(
        "inscription__apprenant", "inscription__annee"
    )


@transaction.atomic
def enregistrer_depense(etablissement, montant, date_depense, categorie, motif, par):
    if montant <= 0:
        raise ErreurMetier("Le montant de la dépense doit être supérieur à zéro.")
    depense = Depense.sans_filtre.create(
        etablissement=etablissement, montant=montant, date_depense=date_depense,
        categorie=categorie, motif=motif.strip(), enregistree_par=par,
    )
    enregistrer_audit(
        etablissement, par, "finance.depense.enregistrement", depense,
        apres={"montant": str(depense.montant), "categorie": depense.categorie},
    )
    return depense


def synthese_financiere(etablissement):
    paiements = Paiement.objects.aggregate(total=Sum("montant"))
    remboursements = Remboursement.objects.aggregate(total=Sum("montant"))
    depenses = Depense.objects.aggregate(total=Sum("montant"))
    total_paiements = (paiements["total"] or Decimal("0")) - (remboursements["total"] or Decimal("0"))
    total_depenses = depenses["total"] or Decimal("0")
    return {
        "total_paiements": total_paiements,
        "nombre_paiements": Paiement.objects.count(),
        "total_remboursements": remboursements["total"] or Decimal("0"),
        "total_depenses": total_depenses,
        "nombre_depenses": Depense.objects.count(),
        "solde": total_paiements - total_depenses,
    }


def rapport_financier(etablissement, debut, fin):
    if debut > fin:
        raise ErreurMetier("La date de début doit précéder la date de fin.")
    paiements = Paiement.objects.filter(date_paiement__gte=debut, date_paiement__lte=fin)
    depenses = Depense.objects.filter(date_depense__gte=debut, date_depense__lte=fin)
    total_paiements = paiements.aggregate(total=Sum("montant"))["total"] or Decimal("0")
    total_remboursements = Remboursement.objects.filter(
        date_remboursement__date__gte=debut, date_remboursement__date__lte=fin
    ).aggregate(total=Sum("montant"))["total"] or Decimal("0")
    total_paiements -= total_remboursements
    total_depenses = depenses.aggregate(total=Sum("montant"))["total"] or Decimal("0")
    par_mode = {
        libelle: paiements.filter(mode=code).aggregate(total=Sum("montant"))["total"] or Decimal("0")
        for code, libelle in Paiement.Mode.choices
    }
    par_categorie = {
        libelle: depenses.filter(categorie=code).aggregate(total=Sum("montant"))["total"] or Decimal("0")
        for code, libelle in Depense.Categorie.choices
    }
    impayes = []
    factures = Facture.objects.exclude(statut__in=[Facture.Statut.SOLDEE, Facture.Statut.ANNULEE]).select_related(
        "inscription__apprenant", "inscription__classe"
    ).prefetch_related("echeances", "paiements")
    for facture in factures:
        exigible = montant_exigible(facture, fin)
        if exigible > 0:
            impayes.append({"facture": facture, "exigible": exigible, "solde": solde_facture(facture)})
    return {
        "debut": debut, "fin": fin, "total_paiements": total_paiements,
        "total_remboursements": total_remboursements,
        "total_depenses": total_depenses, "solde": total_paiements - total_depenses,
        "par_mode": {cle: valeur for cle, valeur in par_mode.items() if valeur},
        "par_categorie": {cle: valeur for cle, valeur in par_categorie.items() if valeur},
        "total_facture": Facture.objects.exclude(statut=Facture.Statut.ANNULEE).aggregate(
            total=Sum("total")
        )["total"] or Decimal("0"),
        "total_impaye": sum((ligne["exigible"] for ligne in impayes), Decimal("0")),
        "impayes": sorted(impayes, key=lambda ligne: ligne["exigible"], reverse=True),
    }
