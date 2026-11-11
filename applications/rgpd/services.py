import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from applications.academique.models import AnneeAcademique
from applications.apprenants.models import Apprenant, Inscription, LienResponsable, ResponsableLegal
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance, ParametresEtablissement
from applications.noyau.services import enregistrer_audit

from .models import Consentement, DemandeRGPD


def apprenants_accessibles(utilisateur, etablissement):
    return Apprenant.sans_filtre.filter(etablissement=etablissement).filter(
        Q(utilisateur=utilisateur) | Q(liens_responsables__responsable__utilisateur=utilisateur)
    ).distinct()


def _iso(valeur):
    if isinstance(valeur, (date, datetime, time)):
        return valeur.isoformat()
    if isinstance(valeur, Decimal):
        return str(valeur)
    return valeur


def exporter_donnees(apprenant, utilisateur):
    if not apprenants_accessibles(utilisateur, apprenant.etablissement).filter(pk=apprenant.pk).exists():
        raise ErreurMetier("Vous ne pouvez consulter que vos propres données ou celles de vos enfants.")
    inscriptions = apprenant.inscriptions.select_related("annee", "niveau", "classe", "programme")
    liens = apprenant.liens_responsables.select_related("responsable")
    from applications.evaluations.models import Note, ResultatPeriode
    from applications.cahier.models import Remise
    from applications.finances.models import Facture, Paiement
    from applications.presences.models import LignePresence
    from applications.admissions.models import Candidature

    notes = Note.objects.filter(inscription__apprenant=apprenant).select_related(
        "composante__configuration__affectation__matiere_niveau__matiere",
        "composante__configuration__periode", "inscription",
    )
    resultats = ResultatPeriode.objects.filter(inscription__apprenant=apprenant).select_related(
        "matiere_niveau__matiere", "periode", "inscription",
    )
    presences = LignePresence.objects.filter(inscription__apprenant=apprenant).select_related("appel")
    paiements = Paiement.objects.filter(apprenant=apprenant)
    factures = Facture.objects.filter(inscription__apprenant=apprenant).prefetch_related(
        "lignes", "echeances", "paiements"
    )
    remises = Remise.objects.filter(inscription__apprenant=apprenant).select_related("devoir")
    consentements = Consentement.objects.filter(apprenant=apprenant)
    candidatures = Candidature.sans_filtre.filter(apprenant_cree=apprenant).select_related("classe", "annee")
    return {
        "export_genere_le": timezone.now().isoformat(),
        "etablissement": apprenant.etablissement.nom,
        "apprenant": {
            "matricule": apprenant.matricule, "nom": apprenant.nom, "prenoms": apprenant.prenoms,
            "sexe": apprenant.get_sexe_display(), "date_naissance": apprenant.date_naissance.isoformat(),
            "lieu_naissance": apprenant.lieu_naissance, "email": apprenant.email,
            "telephone": apprenant.telephone, "adresse": apprenant.adresse,
        },
        "responsables": [{
            "lien": lien.get_lien_display(), "nom": lien.responsable.nom,
            "prenoms": lien.responsable.prenoms, "telephone": lien.responsable.telephone,
            "email": lien.responsable.email,
        } for lien in liens],
        "inscriptions": [{
            "annee": inscription.annee.designation, "niveau": inscription.niveau.nom,
            "programme": inscription.programme.nom if inscription.programme_id else None,
            "classe": inscription.classe.nom if inscription.classe_id else None,
            "statut": inscription.get_statut_display(), "date_demande": _iso(inscription.date_demande),
        } for inscription in inscriptions],
        "notes": [{
            "matiere": note.composante.configuration.affectation.matiere_niveau.matiere.nom,
            "periode": note.composante.configuration.periode.nom,
            "evaluation": note.composante.intitule, "valeur": _iso(note.valeur),
            "etat": note.get_etat_display(),
        } for note in notes],
        "resultats": [{
            "matiere": resultat.matiere_niveau.matiere.nom, "periode": resultat.periode.nom,
            "total": _iso(resultat.total), "bareme": _iso(resultat.bareme_applique),
            "pourcentage": _iso(resultat.pourcentage), "statut": resultat.get_statut_display(),
            "publie": resultat.publie,
        } for resultat in resultats],
        "presences": [{
            "date": _iso(ligne.appel.date), "statut": ligne.get_statut_display(),
            "motif": ligne.motif,
        } for ligne in presences],
        "paiements": [{
            "date": _iso(paiement.date_paiement), "montant": _iso(paiement.montant),
            "motif": paiement.motif, "mode": paiement.get_mode_display(),
        } for paiement in paiements],
        "factures": [{
            "numero": facture.numero, "total": _iso(facture.total), "devise": facture.devise,
            "statut": facture.get_statut_display(), "date_emission": _iso(facture.date_emission),
            "lignes": [{"libelle": ligne.libelle, "montant": _iso(ligne.montant)} for ligne in facture.lignes.all()],
            "echeances": [{
                "libelle": echeance.libelle, "montant": _iso(echeance.montant),
                "date_limite": _iso(echeance.date_limite),
            } for echeance in facture.echeances.all()],
        } for facture in factures],
        "devoirs_remis": [{
            "devoir": remise.devoir.titre, "remise_le": _iso(remise.remise_le),
            "commentaire": remise.commentaire, "appreciation": remise.appreciation,
            "en_retard": remise.en_retard,
            "fichier": remise.fichier.name.rsplit("/", 1)[-1] if remise.fichier else None,
        } for remise in remises],
        "consentements": [{
            "finalite": consentement.get_finalite_display(), "accorde": consentement.accorde,
            "date": _iso(consentement.cree_le), "precision": consentement.note,
        } for consentement in consentements],
        "candidatures": [{
            "reference": str(candidature.reference), "classe_demandee": candidature.classe.nom,
            "annee": candidature.annee.designation, "date_depot": _iso(candidature.date_creation),
            "statut": candidature.get_statut_display(), "message": candidature.message,
            "consentement_donnees": candidature.consentement_donnees,
            "consentement_le": _iso(candidature.consentement_le),
        } for candidature in candidatures],
    }


@transaction.atomic
def enregistrer_consentement(apprenant, finalite, accorde, note, auteur):
    if apprenant.anonymise:
        raise ErreurMetier("Un dossier anonymisé ne peut plus recevoir de consentement.")
    consentement = Consentement.sans_filtre.create(
        etablissement=apprenant.etablissement, apprenant=apprenant,
        finalite=finalite, accorde=accorde, note=note.strip(), enregistre_par=auteur,
    )
    enregistrer_audit(
        apprenant.etablissement, auteur, "rgpd.consentement", consentement,
        apres={"finalite": finalite, "accorde": accorde},
    )
    return consentement


@transaction.atomic
def creer_demande(apprenant, demandeur, type_demande, details=""):
    if apprenant.anonymise:
        raise ErreurMetier("Ce dossier est déjà anonymisé.")
    demande = DemandeRGPD.sans_filtre.create(
        etablissement=apprenant.etablissement, apprenant=apprenant, demandeur=demandeur,
        type=type_demande, details=details.strip(),
        echeance=timezone.localdate() + timedelta(days=30),
    )
    enregistrer_audit(
        apprenant.etablissement, demandeur, "rgpd.demande", demande,
        apres={"type": type_demande},
    )
    return demande


def _anonymiser_compte(utilisateur, etablissement):
    if utilisateur is None:
        return
    if Appartenance.sans_filtre.filter(utilisateur=utilisateur).exclude(etablissement=etablissement).exists():
        return
    if ResponsableLegal.sans_filtre.filter(
        utilisateur=utilisateur, liens_apprenants__apprenant__anonymise=False
    ).exclude(etablissement=etablissement).exists():
        return
    if ResponsableLegal.sans_filtre.filter(
        utilisateur=utilisateur, liens_apprenants__apprenant__anonymise=False,
        etablissement=etablissement,
    ).exists():
        return
    utilisateur.is_active = False
    utilisateur.email = f"anonyme-{utilisateur.pk}@invalid.local"
    utilisateur.username = f"anonyme-{utilisateur.pk}"
    utilisateur.first_name = ""
    utilisateur.last_name = ""
    utilisateur.telephone = ""
    utilisateur.save(update_fields=[
        "is_active", "email", "username", "first_name", "last_name", "telephone",
    ])


@transaction.atomic
def anonymiser_apprenant(apprenant, auteur):
    apprenant = Apprenant.sans_filtre.select_for_update().get(pk=apprenant.pk)
    if apprenant.anonymise:
        raise ErreurMetier("Ce dossier est déjà anonymisé.")
    if Inscription.sans_filtre.filter(
        apprenant=apprenant, annee__statut=AnneeAcademique.Statut.ACTIVE,
        statut__in=Inscription.STATUTS_EN_COURS,
    ).exists():
        raise ErreurMetier("L'effacement est bloqué : l'apprenant a une inscription en cours.")
    responsable_ids = list(
        LienResponsable.sans_filtre.filter(apprenant=apprenant).values_list("responsable_id", flat=True)
    )
    utilisateur_apprenant = apprenant.utilisateur
    if apprenant.photo:
        apprenant.photo.delete(save=False)
    apprenant.nom = "Dossier anonymisé"
    apprenant.prenoms = "Anonyme"
    apprenant.sexe = ""
    apprenant.date_naissance = date(1900, 1, 1)
    apprenant.lieu_naissance = ""
    apprenant.email = ""
    apprenant.telephone = ""
    apprenant.adresse = ""
    apprenant.matricule = f"ANON-{apprenant.pk}"
    apprenant.actif = False
    apprenant.anonymise = True
    apprenant.anonymise_le = timezone.now()
    apprenant.utilisateur = None
    apprenant.save()
    _anonymiser_compte(utilisateur_apprenant, apprenant.etablissement)
    for responsable_id in responsable_ids:
        responsable = ResponsableLegal.sans_filtre.select_for_update().get(pk=responsable_id)
        if LienResponsable.sans_filtre.filter(responsable=responsable).exclude(apprenant=apprenant).exists():
            continue
        utilisateur = responsable.utilisateur
        responsable.nom = "Responsable anonymisé"
        responsable.prenoms = ""
        responsable.telephone = ""
        responsable.email = ""
        responsable.utilisateur = None
        responsable.save(update_fields=["nom", "prenoms", "telephone", "email", "utilisateur"])
        _anonymiser_compte(utilisateur, apprenant.etablissement)
    Consentement.sans_filtre.filter(apprenant=apprenant).update(note="")
    DemandeRGPD.sans_filtre.filter(apprenant=apprenant).update(
        details="", reponse="", demandeur=None
    )
    from applications.admissions.models import Candidature

    Candidature.sans_filtre.filter(apprenant_cree=apprenant).update(
        nom="Dossier anonymisé", prenoms="Anonyme", sexe="", date_naissance=date(1900, 1, 1),
        lieu_naissance="", nom_parent="Parent anonymisé", telephone_parent="", email_parent="",
        message="", consentement_donnees=False, consentement_le=None,
    )
    enregistrer_audit(
        apprenant.etablissement, auteur, "rgpd.anonymisation", apprenant,
        apres={"anonymise": True},
    )
    return apprenant


@transaction.atomic
def traiter_demande(demande, action, reponse, auteur):
    demande = DemandeRGPD.sans_filtre.select_for_update().select_related("apprenant").get(pk=demande.pk)
    if demande.statut != DemandeRGPD.Statut.EN_ATTENTE:
        raise ErreurMetier("Cette demande a déjà été traitée.")
    if action == "refuser":
        if not reponse.strip():
            raise ErreurMetier("Un motif est obligatoire pour refuser une demande.")
        demande.statut = DemandeRGPD.Statut.REFUSEE
    elif action == "traiter":
        if demande.type == DemandeRGPD.Type.EFFACEMENT:
            if demande.apprenant is None:
                raise ErreurMetier("Le dossier associé à cette demande n'existe plus.")
            anonymiser_apprenant(demande.apprenant, auteur)
        elif not reponse.strip():
            raise ErreurMetier("Ajoutez une réponse ou un motif de traitement.")
        demande.statut = DemandeRGPD.Statut.TRAITEE
    else:
        raise ErreurMetier("Action de traitement invalide.")
    demande.reponse = reponse.strip()
    demande.traitee_le = timezone.now()
    demande.save(update_fields=["statut", "reponse", "traitee_le"])
    enregistrer_audit(
        demande.etablissement, auteur, "rgpd.demande_traitement", demande,
        apres={"statut": demande.statut},
    )
    return demande


def dossiers_a_anonymiser(etablissement, date_reference=None):
    date_reference = date_reference or timezone.localdate()
    parametres = ParametresEtablissement.objects.get(etablissement=etablissement)
    annee = date_reference.year - parametres.retention_annees
    date_limite = date_reference.replace(year=annee, day=min(date_reference.day, calendar.monthrange(annee, date_reference.month)[1]))
    inscriptions_actives = Inscription.sans_filtre.filter(
        annee__statut=AnneeAcademique.Statut.ACTIVE, statut__in=Inscription.STATUTS_EN_COURS
    ).values("apprenant_id")
    return Apprenant.sans_filtre.filter(
        etablissement=etablissement, actif=False, anonymise=False
    ).annotate(
        derniere_fin=Max("inscriptions__annee__date_fin")
    ).filter(derniere_fin__lt=date_limite).exclude(pk__in=inscriptions_actives)
