import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta
from zipfile import BadZipFile

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from applications.academique.models import AnneeAcademique, Classe, Niveau, Programme
from applications.apprenants import services as services_apprenants
from applications.apprenants.models import Apprenant, ResponsableLegal
from applications.noyau import saas
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Appartenance, Invitation, Role
from applications.noyau.services import enregistrer_audit

from .models import LotImportation

TAILLE_MAXIMALE = 5 * 1024 * 1024
LIGNES_MAXIMALES = 5000
ALIAS = {
    "nom": {"nom", "name", "lastname", "surname"},
    "prenoms": {"prenoms", "prenom", "first name", "firstname", "given name"},
    "sexe": {"sexe", "sex", "genre"},
    "date_naissance": {"date naissance", "date de naissance", "date_naissance", "birth date", "birthdate"},
    "lieu_naissance": {"lieu naissance", "lieu de naissance", "birthplace"},
    "email": {"email", "e mail", "courriel", "adresse email"},
    "telephone": {"telephone", "phone", "tel", "portable"},
    "adresse": {"adresse", "address"},
    "responsable_nom": {"responsable nom", "nom responsable", "parent nom", "nom parent"},
    "responsable_prenoms": {"responsable prenoms", "prenoms responsable", "parent prenoms"},
    "responsable_telephone": {"responsable telephone", "telephone responsable", "parent telephone"},
    "responsable_email": {"responsable email", "email responsable", "parent email"},
    "niveau": {"niveau", "level"},
    "classe": {"classe", "class", "groupe"},
    "programme": {"programme", "program", "filiere"},
    "role": {"role", "fonction"},
}


def _normaliser(valeur):
    texte = unicodedata.normalize("NFKD", str(valeur or ""))
    texte = "".join(caractere for caractere in texte if not unicodedata.combining(caractere))
    return re.sub(r"[\s_-]+", " ", texte.strip().casefold())


def _lire_lignes(fichier):
    nom = fichier.name
    extension = nom.rsplit(".", 1)[-1].casefold() if "." in nom else ""
    contenu = fichier.read(TAILLE_MAXIMALE + 1)
    if len(contenu) > TAILLE_MAXIMALE:
        raise ErreurMetier("Le fichier dépasse la taille maximale de 5 Mo.")
    if extension == "csv":
        try:
            texte = contenu.decode("utf-8-sig")
        except UnicodeDecodeError as erreur:
            raise ErreurMetier("Le fichier CSV doit être encodé en UTF-8.") from erreur
        apercu = texte[:4096]
        try:
            dialecte = csv.Sniffer().sniff(apercu, delimiters=",;\t")
        except csv.Error:
            dialecte = csv.excel
        lignes = list(csv.reader(io.StringIO(texte), dialect=dialecte))
    elif extension == "xlsx":
        try:
            classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
        except (ValueError, OSError, BadZipFile, InvalidFileException) as erreur:
            raise ErreurMetier("Le fichier Excel est illisible.") from erreur
        feuille = classeur.active
        lignes = [list(ligne) for ligne in feuille.iter_rows(values_only=True)]
        classeur.close()
    else:
        raise ErreurMetier("Format non pris en charge : utilisez un fichier .csv ou .xlsx.")
    if not lignes:
        raise ErreurMetier("Le fichier ne contient aucune ligne.")
    en_tetes = [_normaliser(valeur) for valeur in lignes[0]]
    if not any(en_tetes):
        raise ErreurMetier("La première ligne doit contenir les noms des colonnes.")
    if len(lignes) - 1 > LIGNES_MAXIMALES:
        raise ErreurMetier(f"Le fichier ne peut pas dépasser {LIGNES_MAXIMALES} lignes.")
    correspondances = {}
    for cle, alias in ALIAS.items():
        for index, entete in enumerate(en_tetes):
            if entete in alias:
                correspondances[cle] = index
                break
    donnees = []
    for numero, ligne in enumerate(lignes[1:], start=2):
        if not any(valeur is not None and str(valeur).strip() for valeur in ligne):
            continue
        donnees.append({
            cle: (ligne[index] if index < len(ligne) else "")
            for cle, index in correspondances.items()
        } | {"_numero": numero})
    if not donnees:
        raise ErreurMetier("Le fichier ne contient aucune donnée à importer.")
    return donnees


def _date_naissance(valeur):
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur or "").strip()
    for format_date in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texte, format_date).date()
        except ValueError:
            continue
    raise ErreurMetier("Date de naissance invalide (formats acceptés : AAAA-MM-JJ ou JJ/MM/AAAA).")


def _texte(ligne, cle):
    valeur = ligne.get(cle, "")
    return str(valeur).strip() if valeur is not None else ""


def _preparer_apprenant(etablissement, ligne, annee):
    nom = _texte(ligne, "nom")
    prenoms = _texte(ligne, "prenoms")
    if not nom or not prenoms:
        raise ErreurMetier("Les colonnes nom et prénoms sont obligatoires.")
    naissance = _date_naissance(ligne.get("date_naissance"))
    if naissance > timezone.localdate():
        raise ErreurMetier("La date de naissance ne peut pas être dans le futur.")
    sexe = _normaliser(ligne.get("sexe"))
    if sexe in {"m", "masculin", "homme", "male"}:
        sexe = Apprenant.Sexe.MASCULIN
    elif sexe in {"f", "feminin", "femme", "female"}:
        sexe = Apprenant.Sexe.FEMININ
    else:
        raise ErreurMetier("Le sexe doit être M/masculin ou F/féminin.")
    if Apprenant.sans_filtre.filter(
        etablissement=etablissement,
        nom__iexact=nom, prenoms__iexact=prenoms, date_naissance=naissance
    ).exists():
        raise ErreurMetier("Un dossier identique existe déjà dans cet établissement.")
    resultat = {
        "nom": nom, "prenoms": prenoms, "sexe": sexe, "date_naissance": naissance.isoformat(),
        "lieu_naissance": _texte(ligne, "lieu_naissance"), "email": _texte(ligne, "email"),
        "telephone": _texte(ligne, "telephone"), "adresse": _texte(ligne, "adresse"),
        "responsable_nom": _texte(ligne, "responsable_nom"),
        "responsable_prenoms": _texte(ligne, "responsable_prenoms"),
        "responsable_telephone": _texte(ligne, "responsable_telephone"),
        "responsable_email": _texte(ligne, "responsable_email"),
        "niveau": _texte(ligne, "niveau"), "classe": _texte(ligne, "classe"),
        "programme": _texte(ligne, "programme"),
    }
    for adresse in (resultat["email"], resultat["responsable_email"]):
        if adresse:
            try:
                validate_email(adresse)
            except ValidationError as erreur:
                raise ErreurMetier("Une adresse e-mail du dossier est invalide.") from erreur
    niveau = None
    programme = None
    classe = None
    if resultat["niveau"]:
        filtres = {"nom__iexact": resultat["niveau"]}
        if etablissement.est_universitaire:
            if not resultat["programme"]:
                raise ErreurMetier("Le programme est obligatoire pour un niveau universitaire.")
            programme = Programme.sans_filtre.filter(
                etablissement=etablissement, nom__iexact=resultat["programme"]
            ).first()
            if programme is None:
                raise ErreurMetier(f"Programme introuvable : {resultat['programme']}.")
            filtres["programme"] = programme
        else:
            filtres["programme__isnull"] = True
        niveaux = Niveau.sans_filtre.filter(etablissement=etablissement, **filtres)
        if niveaux.count() != 1:
            raise ErreurMetier(f"Niveau introuvable ou ambigu : {resultat['niveau']}.")
        niveau = niveaux.get()
        if annee is None:
            raise ErreurMetier("Aucune année académique active pour inscrire cet apprenant.")
        if resultat["classe"]:
            if etablissement.est_universitaire:
                raise ErreurMetier("Les établissements universitaires n'utilisent pas de classes.")
            classes = Classe.sans_filtre.filter(
                etablissement=etablissement, niveau=niveau, annee=annee, nom__iexact=resultat["classe"]
            )
            if classes.count() != 1:
                raise ErreurMetier(f"Classe introuvable : {resultat['classe']}.")
            classe = classes.get()
    elif resultat["classe"] or resultat["programme"]:
        raise ErreurMetier("Renseignez un niveau avant la classe ou le programme.")
    resultat["_niveau_id"] = niveau.pk if niveau else None
    resultat["_classe_id"] = classe.pk if classe else None
    resultat["_programme_id"] = programme.pk if programme else None
    return resultat


def _preparer_personnel(ligne):
    nom, prenoms = _texte(ligne, "nom"), _texte(ligne, "prenoms")
    email = _texte(ligne, "email").casefold()
    role = _texte(ligne, "role")
    if not nom or not prenoms or not email or not role:
        raise ErreurMetier("Les colonnes nom, prénoms, e-mail et rôle sont obligatoires.")
    try:
        validate_email(email)
    except ValidationError as erreur:
        raise ErreurMetier("L'adresse e-mail est invalide.") from erreur
    return {"nom": nom, "prenoms": prenoms, "email": email, "role": role}


def analyser_fichier(etablissement, utilisateur, type_import, fichier):
    lignes_brutes = _lire_lignes(fichier)
    annee = AnneeAcademique.sans_filtre.filter(
        etablissement=etablissement, statut=AnneeAcademique.Statut.ACTIVE
    ).first()
    lignes_valides, erreurs = [], []
    identifiants = set()
    for ligne in lignes_brutes:
        numero = ligne["_numero"]
        try:
            if type_import == LotImportation.Type.APPRENANTS:
                resultat = _preparer_apprenant(etablissement, ligne, annee)
                identite = (
                    resultat["nom"].casefold(), resultat["prenoms"].casefold(), resultat["date_naissance"]
                )
            elif type_import == LotImportation.Type.PERSONNEL:
                resultat = _preparer_personnel(ligne)
                role = Role.sans_filtre.filter(
                    etablissement=etablissement, nom__iexact=resultat["role"]
                ).first()
                if role is None:
                    raise ErreurMetier(f"Rôle inconnu dans cet établissement : {resultat['role']}.")
                if role.nom in {"Parent", "Apprenant"}:
                    raise ErreurMetier("Seuls les rôles du personnel peuvent être importés ici.")
                resultat["role"] = role.nom
                if Appartenance.sans_filtre.filter(
                    etablissement=etablissement, utilisateur__email__iexact=resultat["email"]
                ).exists():
                    raise ErreurMetier("Cette adresse appartient déjà à un membre de l'établissement.")
                if Invitation.sans_filtre.filter(
                    etablissement=etablissement,
                    email__iexact=resultat["email"], statut=Invitation.Statut.EN_ATTENTE,
                    date_expiration__gt=timezone.now(),
                ).exists():
                    raise ErreurMetier("Une invitation est déjà en attente pour cette adresse.")
                identite = resultat["email"]
            else:
                raise ErreurMetier("Type d'importation invalide.")
            if identite in identifiants:
                raise ErreurMetier("Cette ligne est un doublon dans le fichier.")
            identifiants.add(identite)
            lignes_valides.append({"numero": numero, "donnees": resultat})
        except ErreurMetier as erreur:
            erreurs.append({"numero": numero, "message": str(erreur)})
    lot = LotImportation.sans_filtre.create(
        etablissement=etablissement, type=type_import, nom_fichier=fichier.name[:255],
        lignes=lignes_valides, erreurs=erreurs, nombre_lignes=len(lignes_brutes),
        cree_par=utilisateur, expire_le=timezone.now() + timedelta(days=1),
    )
    return lot


def _creer_responsable(etablissement, donnees):
    if not donnees["responsable_nom"]:
        return None
    filtres = {
        "nom__iexact": donnees["responsable_nom"],
        "prenoms__iexact": donnees["responsable_prenoms"],
        "telephone": donnees["responsable_telephone"],
    }
    if donnees["responsable_email"]:
        filtres["email__iexact"] = donnees["responsable_email"]
    responsable = ResponsableLegal.sans_filtre.filter(etablissement=etablissement, **filtres).first()
    return responsable or services_apprenants.creer_responsable(
        etablissement, donnees["responsable_nom"], donnees["responsable_prenoms"],
        donnees["responsable_telephone"], donnees["responsable_email"],
    )


@transaction.atomic
def confirmer_importation(lot, utilisateur, url_base):
    if lot.expire_le <= timezone.now():
        raise ErreurMetier("Cet aperçu a expiré. Importez à nouveau le fichier.")
    if not lot.lignes:
        raise ErreurMetier("Aucune ligne valide à importer.")
    resultat = []
    if lot.type == LotImportation.Type.APPRENANTS:
        saas.verifier_quota(lot.etablissement, "apprenants", len(lot.lignes))
        annee = AnneeAcademique.sans_filtre.filter(
            etablissement=lot.etablissement, statut=AnneeAcademique.Statut.ACTIVE
        ).first()
        for ligne in lot.lignes:
            donnees = ligne["donnees"]
            responsable = _creer_responsable(lot.etablissement, donnees)
            apprenant = services_apprenants.creer_apprenant(
                lot.etablissement, donnees["nom"], donnees["prenoms"], donnees["sexe"],
                date.fromisoformat(donnees["date_naissance"]), responsable=responsable,
                lieu_naissance=donnees["lieu_naissance"], email=donnees["email"],
                telephone=donnees["telephone"], adresse=donnees["adresse"],
            )
            if donnees["_niveau_id"]:
                niveau = Niveau.sans_filtre.get(pk=donnees["_niveau_id"], etablissement=lot.etablissement)
                classe = Classe.sans_filtre.get(
                    pk=donnees["_classe_id"], etablissement=lot.etablissement
                ) if donnees["_classe_id"] else None
                programme = Programme.sans_filtre.get(
                    pk=donnees["_programme_id"], etablissement=lot.etablissement
                ) if donnees["_programme_id"] else None
                services_apprenants.creer_inscription(
                    lot.etablissement, apprenant, niveau, classe=classe, programme=programme, par=utilisateur,
                )
            resultat.append(apprenant)
    else:
        saas.verifier_quota(lot.etablissement, "membres", len(lot.lignes))
        for ligne in lot.lignes:
            donnees = ligne["donnees"]
            role = Role.sans_filtre.get(nom=donnees["role"], etablissement=lot.etablissement)
            saas.inviter(lot.etablissement, donnees["email"], role, utilisateur, url_base)
            resultat.append(donnees["email"])
    lot.nombre_importe = len(resultat)
    lot.lignes = []
    lot.save(update_fields=["nombre_importe", "lignes"])
    enregistrer_audit(
        lot.etablissement, utilisateur, "importation.confirmer", lot,
        apres={"type": lot.type, "nombre": lot.nombre_importe, "erreurs": lot.nombre_erreurs},
    )
    return resultat


def annuler_importation(lot, utilisateur):
    lot.lignes = []
    lot.erreurs = []
    lot.save(update_fields=["lignes", "erreurs"])
    enregistrer_audit(lot.etablissement, utilisateur, "importation.annuler", lot)


@transaction.atomic
def nettoyer_apercus_expires():
    lots = LotImportation.sans_filtre.filter(expire_le__lte=timezone.now()).exclude(lignes=[])
    nombre = lots.count()
    lots.update(lignes=[])
    return nombre
