"""Fabriques de données partagées par les tests."""
from datetime import date

from applications.academique import services as academique
from applications.apprenants import services as apprenants
from applications.noyau.models import Etablissement, TypeEtablissement
from applications.noyau.services import creer_etablissement, creer_membre
from applications.pedagogie import services as pedagogie


def monde_scolaire(nom="École Test", activer=True):
    """Établissement scolaire complet : année active, niveau 7e, classes A et B, matière, enseignant."""
    etab = creer_etablissement(nom, TypeEtablissement.SCOLAIRE)
    annee = academique.creer_annee(etab, "2026-2027", date(2026, 9, 1), date(2027, 6, 30), 3)
    if activer:
        academique.activer_annee(annee)
    n7 = academique.creer_niveau(etab, "7e année")
    n8 = academique.creer_niveau(etab, "8e année")
    classe_a = academique.creer_classe(n7, annee, "7e A")
    classe_b = academique.creer_classe(n7, annee, "7e B")
    maths = pedagogie.creer_matiere(etab, "Mathématiques")
    mn = pedagogie.definir_matiere_niveau(annee, n7, maths, 100)
    prof = creer_membre(etab, f"prof_{etab.pk}", f"prof{etab.pk}@ecole.test", "MotDePasse!2026", "Enseignant")
    secretaire = creer_membre(etab, f"sec_{etab.pk}", f"sec{etab.pk}@ecole.test", "MotDePasse!2026", "Secrétaire")
    directeur = creer_membre(etab, f"dir_{etab.pk}", f"dir{etab.pk}@ecole.test", "MotDePasse!2026", "Directeur")
    affectation = pedagogie.affecter_enseignant(prof, mn, classe_a)
    return {
        "etab": etab, "annee": annee, "n7": n7, "n8": n8, "classe_a": classe_a, "classe_b": classe_b,
        "maths": maths, "mn": mn, "prof": prof, "secretaire": secretaire, "directeur": directeur,
        "affectation": affectation, "periode1": annee.periodes.get(ordre=1),
    }


def inscrire(monde, nom, classe=None, valider=True):
    apprenant = apprenants.creer_apprenant(monde["etab"], nom, "Test", "M", date(2013, 5, 1))
    inscription = apprenants.creer_inscription(monde["etab"], apprenant, monde["n7"], classe=classe or monde["classe_a"])
    if valider:
        apprenants.decider_inscription(inscription, "VALIDER", monde["secretaire"].utilisateur)
        inscription.refresh_from_db()
    return inscription


def monde_universitaire(nom="Université Test"):
    etab = creer_etablissement(nom, TypeEtablissement.UNIVERSITAIRE)
    annee = academique.creer_annee(etab, "2026-2027", date(2026, 9, 1), date(2027, 7, 31), 2)
    academique.activer_annee(annee)
    faculte = academique.creer_faculte(etab, "Faculté des Sciences")
    programme = academique.creer_programme(faculte, "Informatique")
    niveau = academique.creer_niveau(etab, "Licence 1", programme)
    return {"etab": etab, "annee": annee, "faculte": faculte, "programme": programme, "niveau": niveau}
