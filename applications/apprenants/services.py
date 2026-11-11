"""Services métier : dossiers apprenants et cycle de vie des inscriptions."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from applications.academique.models import Classe, Niveau
from applications.academique.services import exiger_annee_active
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import TypeEtablissement
from applications.noyau.services import enregistrer_audit, servir_numero

from .models import (
    Apprenant, DecisionInscription, IncidentDisciplinaire, Inscription,
    LienResponsable, ResponsableLegal,
)


@transaction.atomic
def creer_apprenant(
    etablissement, nom, prenoms, sexe, date_naissance, responsable=None, lien="TUTEUR", par=None, **extra
):
    """Enregistre le dossier permanent. Le matricule est généré automatiquement (AAAA-NNNNN)."""
    from applications.noyau.saas import verifier_quota

    if date_naissance > timezone.localdate():
        raise ErreurMetier("La date de naissance ne peut pas être dans le futur.")
    verifier_quota(etablissement, "apprenants")
    numero = servir_numero(etablissement, "matricule")
    matricule = f"{timezone.localdate().year}-{numero:05d}"
    apprenant = Apprenant.sans_filtre.create(
        etablissement=etablissement, matricule=matricule, nom=nom.strip().upper(), prenoms=prenoms.strip(),
        sexe=sexe, date_naissance=date_naissance, **extra,
    )
    if responsable is not None:
        if etablissement.type != TypeEtablissement.SCOLAIRE:
            raise ErreurMetier("Les responsables légaux sont réservés aux écoles classiques.")
        if responsable.etablissement_id != etablissement.pk:
            raise ErreurMetier("Ce responsable appartient à un autre établissement.")
        LienResponsable.sans_filtre.create(
            etablissement=etablissement, apprenant=apprenant, responsable=responsable, lien=lien, principal=True
        )
    enregistrer_audit(
        etablissement, par, "apprenant.creation", apprenant,
        apres={"matricule": matricule, "nom": apprenant.nom, "prenoms": apprenant.prenoms},
    )
    return apprenant


@transaction.atomic
def modifier_apprenant(apprenant, par=None, **donnees):
    apprenant = Apprenant.sans_filtre.select_for_update().get(pk=apprenant.pk)
    if apprenant.anonymise:
        raise ErreurMetier("Un dossier anonymisé ne peut plus être modifié.")

    champs = (
        "nom", "prenoms", "sexe", "date_naissance", "lieu_naissance",
        "email", "telephone", "adresse",
    )
    avant = {champ: getattr(apprenant, champ) for champ in champs}
    lien_principal = LienResponsable.sans_filtre.select_for_update().select_related(
        "responsable"
    ).filter(apprenant=apprenant, principal=True).first()
    nom_responsable = (donnees.get("responsable_nom") or "").strip()
    if nom_responsable:
        avant["responsable"] = (
            {
                "nom": lien_principal.responsable.nom,
                "prenoms": lien_principal.responsable.prenoms,
                "telephone": lien_principal.responsable.telephone,
                "email": lien_principal.responsable.email,
                "lien": lien_principal.lien,
            }
            if lien_principal else None
        )
    for champ in champs:
        valeur = donnees.get(champ)
        if champ in ("nom", "prenoms"):
            valeur = valeur.strip()
            if champ == "nom":
                valeur = valeur.upper()
        setattr(apprenant, champ, valeur)
    champs_modifies = list(champs)
    if donnees.get("photo"):
        apprenant.photo = donnees["photo"]
        champs_modifies.append("photo")
    try:
        apprenant.save(update_fields=champs_modifies)
    except ValidationError as erreur:
        raise ErreurMetier("; ".join(erreur.messages)) from erreur

    if nom_responsable:
        if lien_principal is None:
            responsable = creer_responsable(
                apprenant.etablissement,
                nom_responsable,
                donnees.get("responsable_prenoms", ""),
                donnees.get("responsable_telephone", ""),
                donnees.get("responsable_email", ""),
            )
            LienResponsable.sans_filtre.create(
                etablissement=apprenant.etablissement,
                apprenant=apprenant,
                responsable=responsable,
                lien=donnees.get("responsable_lien") or LienResponsable.Lien.TUTEUR,
                principal=True,
            )
        else:
            responsable = lien_principal.responsable
            responsable.nom = nom_responsable
            responsable.prenoms = donnees.get("responsable_prenoms", "").strip()
            responsable.telephone = donnees.get("responsable_telephone", "").strip()
            responsable.email = donnees.get("responsable_email", "").strip()
            try:
                responsable.save(update_fields=["nom", "prenoms", "telephone", "email"])
                lien_principal.lien = donnees.get("responsable_lien") or lien_principal.lien
                lien_principal.save(update_fields=["lien"])
            except ValidationError as erreur:
                raise ErreurMetier("; ".join(erreur.messages)) from erreur

    apres = {champ: getattr(apprenant, champ) for champ in champs}
    if nom_responsable:
        responsable = lien_principal.responsable if lien_principal else responsable
        lien = lien_principal.lien if lien_principal else donnees.get("responsable_lien")
        apres["responsable"] = {
            "nom": responsable.nom,
            "prenoms": responsable.prenoms,
            "telephone": responsable.telephone,
            "email": responsable.email,
            "lien": lien,
        }
    enregistrer_audit(
        apprenant.etablissement, par, "apprenant.modification", apprenant,
        avant=avant, apres=apres,
    )
    return apprenant


def creer_responsable(etablissement, nom, prenoms="", telephone="", email=""):
    if etablissement.type != TypeEtablissement.SCOLAIRE:
        raise ErreurMetier("Les responsables légaux sont réservés aux écoles classiques.")
    return ResponsableLegal.sans_filtre.create(
        etablissement=etablissement, nom=nom, prenoms=prenoms, telephone=telephone, email=email
    )


def _verifier_coherence(etablissement, annee, niveau, classe, programme):
    if niveau.etablissement_id != etablissement.pk or annee.etablissement_id != etablissement.pk:
        raise ErreurMetier("Niveau ou année d'un autre établissement.")
    if programme is not None and (
        programme.etablissement_id != etablissement.pk
        or programme.faculte.etablissement_id != etablissement.pk
    ):
        raise ErreurMetier("Le programme appartient à un autre établissement.")
    if niveau.programme_id and (
        niveau.programme.etablissement_id != etablissement.pk
        or niveau.programme.faculte.etablissement_id != etablissement.pk
    ):
        raise ErreurMetier("Le programme du niveau appartient à un autre établissement.")
    if etablissement.est_universitaire:
        if programme is None:
            raise ErreurMetier("Le programme est obligatoire pour une inscription universitaire.")
        if niveau.programme_id != programme.pk:
            raise ErreurMetier("Le niveau choisi n'appartient pas à ce programme.")
        if classe is not None:
            raise ErreurMetier("Les universités n'utilisent pas de classes.")
    else:
        if programme is not None:
            raise ErreurMetier("Un établissement scolaire n'a pas de programme.")
        if classe is not None:
            if (
                classe.etablissement_id != etablissement.pk
                or classe.niveau.etablissement_id != etablissement.pk
                or classe.annee.etablissement_id != etablissement.pk
            ):
                raise ErreurMetier("La classe appartient à un autre établissement.")
            if classe.niveau_id != niveau.pk:
                raise ErreurMetier("La classe choisie n'appartient pas au niveau demandé.")
            if classe.annee_id != annee.pk:
                raise ErreurMetier("La classe choisie appartient à une autre année académique.")


def verifier_capacite_classe(classe, inscription=None, verrouiller=False):
    """Vérifie les places disponibles en ne comptant que les inscriptions validées."""
    if classe is None:
        return
    if verrouiller:
        classe = Classe.sans_filtre.select_for_update().get(pk=classe.pk)
    if classe.effectif_max is None:
        return
    inscriptions = Inscription.sans_filtre.filter(classe=classe, statut=Inscription.Statut.VALIDEE)
    if verrouiller:
        inscriptions = inscriptions.select_for_update()
    if inscription is not None and inscription.pk is not None:
        inscriptions = inscriptions.exclude(pk=inscription.pk)
    if len(list(inscriptions.values_list("pk", flat=True))) >= classe.effectif_max:
        raise ErreurMetier(f"La classe « {classe} » a atteint son effectif maximal.")


def raison_blocage_correction_validee(inscription):
    """Un niveau validé ne se corrige qu'avant la production de données académiques."""
    if inscription.statut != Inscription.Statut.VALIDEE:
        return "Seule une inscription validée peut utiliser la correction de niveau."
    if Inscription.sans_filtre.filter(
        apprenant_id=inscription.apprenant_id,
        annee__date_debut__gt=inscription.annee.date_debut,
        statut__in=Inscription.STATUTS_EN_COURS,
    ).exists():
        return "Une inscription ultérieure est déjà en cours pour cet apprenant."

    dependances = (
        ("notes", "des notes"),
        ("historique_notes", "un historique de notes"),
        ("resultats", "des résultats"),
        ("documents_resultat", "un bulletin"),
        ("lignes_presence", "des présences"),
        ("tentatives_quiz", "des tentatives de quiz"),
        ("remises_devoirs", "des travaux remis"),
    )
    for relation, libelle in dependances:
        if getattr(inscription, relation).exists():
            return f"Cette inscription comporte déjà {libelle} : son niveau ne peut plus être corrigé."
    return ""


@transaction.atomic
def creer_inscription(
    etablissement, apprenant, niveau, classe=None, programme=None,
    type_inscription=Inscription.Type.NOUVELLE, par=None,
):
    """Crée une demande d'inscription (statut EN_ATTENTE automatique) pour l'année active."""
    annee = exiger_annee_active(etablissement)
    if apprenant.etablissement_id != etablissement.pk:
        raise ErreurMetier("Cet apprenant appartient à un autre établissement.")
    _verifier_coherence(etablissement, annee, niveau, classe, programme)
    verifier_capacite_classe(classe)
    Apprenant.sans_filtre.select_for_update().get(pk=apprenant.pk)
    if Inscription.sans_filtre.filter(
        apprenant=apprenant, annee=annee, statut__in=Inscription.STATUTS_EN_COURS
    ).exists():
        raise ErreurMetier(f"{apprenant} a déjà une inscription pour l'année {annee}.")
    inscription = Inscription.sans_filtre.create(
        etablissement=etablissement, apprenant=apprenant, annee=annee, type=type_inscription,
        niveau=niveau, classe=classe, programme=programme, creee_par=par if getattr(par, "pk", None) else None,
    )
    enregistrer_audit(etablissement, par, "inscription.creation", inscription)
    return inscription


@transaction.atomic
def modifier_inscription(
    inscription, apprenant, niveau, classe=None, programme=None,
    type_inscription=Inscription.Type.NOUVELLE, par=None, motif_correction="",
):
    inscription = Inscription.sans_filtre.select_for_update().get(pk=inscription.pk)
    correction_validee = inscription.statut == Inscription.Statut.VALIDEE
    if correction_validee:
        raison = raison_blocage_correction_validee(inscription)
        if raison:
            raise ErreurMetier(raison)
        if apprenant.pk != inscription.apprenant_id or type_inscription != inscription.type:
            raise ErreurMetier("Une correction après validation ne peut pas changer l’apprenant ni le type.")
        if not (motif_correction or "").strip():
            raise ErreurMetier("Un motif est obligatoire pour corriger une inscription validée.")
    elif inscription.statut not in (
        Inscription.Statut.EN_ATTENTE, Inscription.Statut.CORRECTION_DEMANDEE,
    ):
        raise ErreurMetier(
            "Seules les inscriptions en attente ou en correction peuvent être modifiées. "
            "Pour une inscription validée, utilisez le changement de classe."
        )
    if apprenant.etablissement_id != inscription.etablissement_id:
        raise ErreurMetier("Cet apprenant appartient à un autre établissement.")

    Apprenant.sans_filtre.select_for_update().get(pk=apprenant.pk)
    _verifier_coherence(inscription.etablissement, inscription.annee, niveau, classe, programme)
    verifier_capacite_classe(classe, inscription=inscription, verrouiller=True)

    champs = ("apprenant", "niveau", "classe", "programme", "type")
    avant = {
        "apprenant": str(inscription.apprenant),
        "niveau": str(inscription.niveau),
        "classe": str(inscription.classe) if inscription.classe else None,
        "programme": str(inscription.programme) if inscription.programme else None,
        "type": inscription.type,
    }
    inscription.apprenant = apprenant
    inscription.niveau = niveau
    inscription.classe = classe
    inscription.programme = programme
    inscription.type = type_inscription
    try:
        inscription.save(update_fields=champs)
    except ValidationError as erreur:
        raise ErreurMetier("; ".join(erreur.messages)) from erreur
    apres = {
        "apprenant": str(inscription.apprenant),
        "niveau": str(inscription.niveau),
        "classe": str(inscription.classe) if inscription.classe else None,
        "programme": str(inscription.programme) if inscription.programme else None,
        "type": inscription.type,
    }
    enregistrer_audit(
        inscription.etablissement, par, "inscription.modification", inscription,
        avant=avant, apres=apres, motif=motif_correction.strip(),
    )
    return inscription


@transaction.atomic
def decider_inscription(inscription, decision, auteur, motif=""):
    """Valide, rejette ou demande une correction. La décision est tracée (auteur, date, motif)."""
    inscription = Inscription.sans_filtre.select_for_update().get(pk=inscription.pk)
    if inscription.statut not in (Inscription.Statut.EN_ATTENTE, Inscription.Statut.CORRECTION_DEMANDEE):
        raise ErreurMetier("Cette inscription a déjà fait l'objet d'une décision définitive.")
    D = DecisionInscription.Decision
    if decision in (D.REJETER, D.DEMANDER_CORRECTION) and not motif.strip():
        raise ErreurMetier("Un motif est obligatoire pour rejeter ou demander une correction.")
    nouveau_statut = {
        D.VALIDER: Inscription.Statut.VALIDEE,
        D.REJETER: Inscription.Statut.REJETEE,
        D.DEMANDER_CORRECTION: Inscription.Statut.CORRECTION_DEMANDEE,
    }[decision]
    if decision == D.VALIDER and not inscription.annee.est_active:
        raise ErreurMetier("L'année académique de cette inscription n'est plus active.")
    if decision == D.VALIDER:
        verifier_capacite_classe(inscription.classe, inscription=inscription, verrouiller=True)
    ancien = inscription.statut
    inscription.statut = nouveau_statut
    inscription.save(update_fields=["statut"])
    if decision == D.VALIDER:
        from applications.finances.services import generer_facture

        generer_facture(inscription, auteur)
    DecisionInscription.sans_filtre.create(
        etablissement=inscription.etablissement, inscription=inscription, decision=decision,
        motif=motif.strip(), auteur=auteur,
    )
    enregistrer_audit(
        inscription.etablissement, auteur, "inscription.decision", inscription,
        avant={"statut": ancien}, apres={"statut": nouveau_statut}, motif=motif,
    )
    return inscription


@transaction.atomic
def changer_classe(inscription, classe, par=None):
    if inscription.statut != Inscription.Statut.VALIDEE:
        raise ErreurMetier("Seule une inscription validée peut changer de classe.")
    _verifier_coherence(inscription.etablissement, inscription.annee, inscription.niveau, classe, None)
    verifier_capacite_classe(classe, inscription=inscription, verrouiller=True)
    ancienne = inscription.classe
    inscription.classe = classe
    inscription.save(update_fields=["classe"])
    enregistrer_audit(
        inscription.etablissement, par, "inscription.changement_classe", inscription,
        avant={"classe": str(ancienne)}, apres={"classe": str(classe)},
    )
    return inscription


@transaction.atomic
def definir_decision_fin_annee(inscription, decision, par=None):
    if inscription.statut != Inscription.Statut.VALIDEE:
        raise ErreurMetier("Seule une inscription validée peut recevoir une décision de fin d'année.")
    inscription.decision_fin_annee = decision
    inscription.save(update_fields=["decision_fin_annee"])
    enregistrer_audit(inscription.etablissement, par, "inscription.decision_fin_annee", inscription, apres={"decision": decision})
    return inscription


def niveau_suivant(niveau):
    return (
        Niveau.sans_filtre.filter(
            etablissement=niveau.etablissement, programme=niveau.programme, ordre__gt=niveau.ordre
        )
        .order_by("ordre")
        .first()
    )


@transaction.atomic
def reinscrire(inscription_precedente, par=None, classe=None):
    """Prépare l'inscription de la nouvelle année à partir de la décision de fin d'année.

    Le dossier de l'apprenant n'est jamais recréé : seule une nouvelle inscription est ajoutée.
    """
    D = Inscription.DecisionFinAnnee
    decision = inscription_precedente.decision_fin_annee
    if decision == D.PASSAGE:
        niveau = niveau_suivant(inscription_precedente.niveau)
        if niveau is None:
            raise ErreurMetier("Il n'existe pas de niveau supérieur : définissez la décision « Diplômé ».")
        type_inscription = Inscription.Type.REINSCRIPTION
    elif decision == D.REDOUBLEMENT:
        niveau = inscription_precedente.niveau
        type_inscription = Inscription.Type.REDOUBLEMENT
    else:
        raise ErreurMetier("Définissez d'abord une décision de passage ou de redoublement.")
    return creer_inscription(
        inscription_precedente.etablissement, inscription_precedente.apprenant, niveau, classe=classe,
        programme=inscription_precedente.programme, type_inscription=type_inscription, par=par,
    )


@transaction.atomic
def enregistrer_incident(inscription, date_incident, categorie, description, mesure="", confidentiel=False, par=None):
    if inscription.statut != Inscription.Statut.VALIDEE:
        raise ErreurMetier("Un incident ne peut être rattaché qu'à une inscription validée.")
    description = (description or "").strip()
    if not description:
        raise ErreurMetier("La description de l'incident est obligatoire.")
    if categorie not in dict(IncidentDisciplinaire.Categorie.choices):
        raise ErreurMetier("La catégorie de l'incident est invalide.")
    incident = IncidentDisciplinaire.sans_filtre.create(
        etablissement=inscription.etablissement, inscription=inscription,
        date_incident=date_incident, categorie=categorie, description=description,
        mesure=(mesure or "").strip(), confidentiel=confidentiel, enregistre_par=par,
    )
    enregistrer_audit(
        inscription.etablissement, par, "apprenant.incident_disciplinaire", incident,
        apres={"categorie": categorie, "date": date_incident.isoformat(), "confidentiel": confidentiel},
    )
    return incident
