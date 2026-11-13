from io import BytesIO

from django.contrib.staticfiles import finders
from django.db import transaction
from PIL import Image, ImageOps
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.code128 import Code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from applications.academique.models import AnneeAcademique
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit
from applications.pedagogie.models import AffectationEnseignant

from .models import BadgeGenere

LARGEUR_MODELE = 1536
HAUTEUR_MODELE = 1024
LARGEUR_CARTE = 260
HAUTEUR_CARTE = LARGEUR_CARTE * HAUTEUR_MODELE / LARGEUR_MODELE


def _dessiner_qr(document, texte, x, y, taille):
    code = QrCodeWidget(texte)
    x_min, y_min, x_max, y_max = code.getBounds()
    largeur, hauteur = x_max - x_min, y_max - y_min
    dessin = Drawing(
        taille, taille,
        transform=[taille / largeur, 0, 0, taille / hauteur, -x_min * taille / largeur, -y_min * taille / hauteur],
    )
    dessin.add(code)
    renderPDF.draw(dessin, document, x, y)


def _donnees_badge(badge, affectations_par_enseignant, annee_active):
    if badge.type_badge == BadgeGenere.Type.APPRENANT:
        inscription = badge.inscription
        apprenant = badge.inscription.apprenant
        programme = inscription.programme or inscription.niveau.programme
        if badge.classe_id:
            lignes = [
                ("Nom", apprenant.nom),
                ("Prénom", apprenant.prenoms),
                ("Matricule", apprenant.matricule),
                ("Classe", badge.classe.nom),
                ("Niveau", inscription.niveau.nom),
                ("Année", inscription.annee.designation),
                ("École", badge.etablissement.nom),
            ]
        else:
            lignes = [
                ("Nom", apprenant.nom),
                ("Prénom", apprenant.prenoms),
                ("Matricule", apprenant.matricule),
                ("Faculté", programme.faculte.nom if programme else "—"),
                ("Département", "—"),
                ("Programme", programme.nom if programme else "—"),
                ("Niveau", inscription.niveau.nom),
            ]
        return {
            "nom": f"{apprenant.prenoms} {apprenant.nom}".strip(),
            "photo": apprenant.photo,
            "lignes": lignes,
            "reference": apprenant.matricule,
            "annee": inscription.annee.designation,
        }

    appartenance = badge.appartenance
    utilisateur = appartenance.utilisateur
    matieres = []
    facultes = []
    for affectation in affectations_par_enseignant.get(appartenance.pk, ()):
        matiere = affectation.matiere_niveau.matiere.nom
        if matiere not in matieres:
            matieres.append(matiere)
        programme = affectation.matiere_niveau.niveau.programme
        if programme and programme.faculte.nom not in facultes:
            facultes.append(programme.faculte.nom)
    return {
        "nom": utilisateur.get_full_name() or utilisateur.username,
        "photo": utilisateur.photo,
        "lignes": [
            ("Nom", utilisateur.get_full_name() or utilisateur.username),
            ("Rôle", appartenance.role.nom),
            ("Matières", ", ".join(matieres[:2]) or "—"),
            ("Faculté", ", ".join(facultes[:2]) or "—"),
            ("Identifiant", utilisateur.username),
        ],
        "reference": utilisateur.username,
        "annee": annee_active.designation if annee_active else "—",
    }


def _coordonnees(carte_x, carte_y, x, y):
    facteur = LARGEUR_CARTE / LARGEUR_MODELE
    return carte_x + x * facteur, carte_y + HAUTEUR_CARTE - y * facteur


def _masquer_zone(document, carte_x, carte_y, x1, y1, x2, y2, couleur):
    facteur = LARGEUR_CARTE / LARGEUR_MODELE
    document.setFillColor(colors.HexColor(couleur))
    document.rect(
        carte_x + x1 * facteur, carte_y + HAUTEUR_CARTE - y2 * facteur,
        (x2 - x1) * facteur, (y2 - y1) * facteur, fill=1, stroke=0,
    )


def _dessiner_texte(document, carte_x, carte_y, texte, x, y, taille, couleur, largeur_max):
    texte = str(texte or "—").replace("\n", " ")[:90]
    facteur = LARGEUR_CARTE / LARGEUR_MODELE
    largeur = largeur_max * facteur
    taille_effective = taille
    while taille_effective > 5 and document.stringWidth(texte, "Helvetica-Bold", taille_effective) > largeur:
        taille_effective -= 0.25
    position_x, position_y = _coordonnees(carte_x, carte_y, x, y)
    document.setFillColor(colors.HexColor(couleur))
    document.setFont("Helvetica-Bold", taille_effective)
    document.drawString(position_x, position_y, texte)


def _recadrer_photo(source, dimensions):
    source = ImageOps.exif_transpose(source).convert("RGBA")
    fond = Image.new("RGBA", source.size, (255, 255, 255, 255))
    fond.alpha_composite(source)
    return ImageOps.fit(
        fond.convert("RGB"), dimensions, method=Image.Resampling.LANCZOS,
    )


def _dessiner_photo(document, carte_x, carte_y, donnees, type_badge):
    zone = (68, 238, 468, 718) if type_badge == BadgeGenere.Type.APPRENANT else (68, 238, 469, 716)
    x1, y1, x2, y2 = zone
    facteur = LARGEUR_CARTE / LARGEUR_MODELE
    x = carte_x + x1 * facteur
    y = carte_y + HAUTEUR_CARTE - y2 * facteur
    largeur, hauteur = (x2 - x1) * facteur, (y2 - y1) * facteur

    document.saveState()
    chemin = document.beginPath()
    chemin.roundRect(x, y, largeur, hauteur, 8)
    document.clipPath(chemin, stroke=0, fill=0)
    photo = donnees["photo"]
    if photo:
        with photo.open("rb") as fichier:
            with Image.open(fichier) as source:
                image = ImageReader(_recadrer_photo(source, (x2 - x1, y2 - y1)))
        document.drawImage(
            image, x, y, largeur, hauteur,
        )
    else:
        document.setFillColor(colors.HexColor("#e9edf5"))
        document.rect(x, y, largeur, hauteur, fill=1, stroke=0)
        initiales = "".join(mot[0] for mot in donnees["nom"].split() if mot)[:2].upper() or "?"
        document.setFillColor(colors.HexColor("#193b66"))
        document.setFont("Helvetica-Bold", 24)
        document.drawCentredString(x + largeur / 2, y + hauteur / 2, initiales)
    document.restoreState()

    document.setStrokeColor(colors.HexColor("#123d83"))
    document.setLineWidth(1.3)
    document.roundRect(x, y, largeur, hauteur, 8, fill=0, stroke=1)


def _dessiner_identite_etablissement(document, etablissement, carte_x, carte_y):
    _masquer_zone(document, carte_x, carte_y, 24, 22, 319, 210, "#123a80")
    facteur = LARGEUR_CARTE / LARGEUR_MODELE
    x = carte_x + 45 * facteur
    y = carte_y + HAUTEUR_CARTE - 177 * facteur
    largeur, hauteur = 250 * facteur, 142 * facteur
    if etablissement.logo:
        with etablissement.logo.open("rb") as fichier:
            logo = ImageReader(BytesIO(fichier.read()))
        document.drawImage(
            logo, x, y, largeur, hauteur, preserveAspectRatio=True, anchor="c", mask="auto",
        )
        return

    monogramme = etablissement.nom_court or etablissement.nom
    initiales = "".join(mot[0] for mot in monogramme.split() if mot)[:2].upper() or "?"
    centre_x, centre_y = x + largeur / 2, y + hauteur / 2
    rayon = min(largeur, hauteur) * 0.38
    document.setStrokeColor(colors.HexColor("#f5c52e"))
    document.setLineWidth(1.2)
    document.circle(centre_x, centre_y, rayon, fill=0, stroke=1)
    document.setFillColor(colors.white)
    document.setFont("Helvetica-Bold", 15)
    document.drawCentredString(centre_x, centre_y - 5, initiales)


def _dessiner_signature(document, etablissement, carte_x, carte_y):
    _masquer_zone(document, carte_x, carte_y, 1170, 865, 1510, 1000, "#f7f8fc")
    x1, y1 = _coordonnees(carte_x, carte_y, 1195, 948)
    x2, y2 = _coordonnees(carte_x, carte_y, 1490, 948)
    document.setStrokeColor(colors.HexColor("#193b66"))
    document.setLineWidth(0.7)
    document.line(x1, y1, x2, y2)
    role = "Le Recteur" if etablissement.est_universitaire else "La Direction"
    _dessiner_texte(document, carte_x, carte_y, role, 1270, 984, 7.5, "#193b66", 220)


def _dessiner_code_barres(document, texte, x, y, largeur, hauteur):
    valeur = "".join(caractere for caractere in str(texte) if caractere.isascii())[:28] or "0"
    code = Code128(valeur, barWidth=0.55, barHeight=hauteur, humanReadable=False)
    facteur = min(largeur / code.width, hauteur / code.height)
    document.saveState()
    document.setFillColor(colors.black)
    document.translate(x, y)
    document.scale(facteur, facteur)
    code.drawOn(document, 0, 0)
    document.restoreState()


def _dessiner_badge_modele(
    document, etablissement, badge, carte_x, carte_y, images,
    affectations_par_enseignant, annee_active,
):
    type_badge = badge.type_badge
    image = images[type_badge]
    document.drawImage(image, carte_x, carte_y, LARGEUR_CARTE, HAUTEUR_CARTE)
    donnees = _donnees_badge(badge, affectations_par_enseignant, annee_active)
    facteur = LARGEUR_CARTE / LARGEUR_MODELE

    _masquer_zone(document, carte_x, carte_y, 350, 34, 1435, 120, "#123a80")
    _dessiner_texte(document, carte_x, carte_y, etablissement.nom, 388, 95, 12, "#ffffff", 1015)
    _masquer_zone(document, carte_x, carte_y, 350, 120, 1200, 184, "#123a80")
    slogan = etablissement.slogan or "Savoir · Former · Réussir"
    _dessiner_texte(document, carte_x, carte_y, slogan, 390, 160, 7.5, "#ffffff", 760)
    _dessiner_identite_etablissement(document, etablissement, carte_x, carte_y)
    _dessiner_photo(document, carte_x, carte_y, donnees, type_badge)
    _masquer_zone(document, carte_x, carte_y, 488, 238, 1510, 684, "#f5f7fb")
    if type_badge == BadgeGenere.Type.APPRENANT:
        positions = (302, 370, 438, 493, 548, 605, 660)
        _masquer_zone(document, carte_x, carte_y, 190, 748, 570, 852, "#123a80")
        x_libelle, x_valeur = 500, 720
        qr_zone = (1285, 632, 1498, 837)
        code_zone = (660, 704, 1218, 819)
        _masquer_zone(document, carte_x, carte_y, 642, 692, 1235, 871, "#ffffff")
        code_etiquette_y = 858
    else:
        positions = (328, 397, 470, 542, 615)
        _masquer_zone(document, carte_x, carte_y, 190, 744, 570, 856, "#123a80")
        x_libelle, x_valeur = 510, 740
        qr_zone = (1282, 628, 1497, 838)
        code_zone = (640, 680, 1253, 826)
        _masquer_zone(document, carte_x, carte_y, 625, 660, 1260, 848, "#ffffff")
        _masquer_zone(document, carte_x, carte_y, 818, 870, 1165, 958, "#f5c52e")
        _dessiner_texte(document, carte_x, carte_y, "Année académique", 862, 901, 7.5, "#102e60", 280)
        _dessiner_texte(document, carte_x, carte_y, donnees["annee"], 880, 945, 10, "#102e60", 250)

    _dessiner_signature(document, etablissement, carte_x, carte_y)
    for (libelle, valeur), y in zip(donnees["lignes"], positions):
        _dessiner_texte(document, carte_x, carte_y, f"{libelle} :", x_libelle, y, 7.3, "#123a80", 215)
        _dessiner_texte(document, carte_x, carte_y, valeur, x_valeur, y, 8.2, "#101820", 540)

    if type_badge == BadgeGenere.Type.APPRENANT:
        libelle_type = "ÉTUDIANT" if etablissement.est_universitaire else "APPRENANT"
        texte_type = "CARTE UNIVERSITAIRE" if etablissement.est_universitaire else "CARTE D'IDENTIFICATION"
        _dessiner_texte(document, carte_x, carte_y, libelle_type, 214, 797, 10.5, "#ffffff", 320)
        _dessiner_texte(document, carte_x, carte_y, texte_type, 214, 830, 7.5, "#ffffff", 340)
    else:
        _dessiner_texte(document, carte_x, carte_y, "ENSEIGNANT", 245, 795, 10, "#ffffff", 310)

    qr_x1, qr_y1, qr_x2, qr_y2 = qr_zone
    _masquer_zone(document, carte_x, carte_y, qr_x1, qr_y1, qr_x2, qr_y2, "#ffffff")
    qr_x, qr_top = _coordonnees(carte_x, carte_y, qr_x1 + 8, qr_y1 + 8)
    _dessiner_qr(document, str(badge.jeton), qr_x, qr_top - (qr_y2 - qr_y1 - 16) * facteur,
                  (qr_y2 - qr_y1 - 16) * facteur)

    code_x1, code_y1, code_x2, code_y2 = code_zone
    code_x, code_top = _coordonnees(carte_x, carte_y, code_x1, code_y1)
    _dessiner_code_barres(
        document, donnees["reference"], code_x, code_top - (code_y2 - code_y1) * facteur,
        (code_x2 - code_x1) * facteur, (code_y2 - code_y1) * facteur,
    )
    if type_badge == BadgeGenere.Type.APPRENANT:
        _dessiner_texte(
            document, carte_x, carte_y, donnees["reference"], code_x1 + 90,
            code_etiquette_y, 7.6, "#101820", 420,
        )


def _creer_pdf(etablissement, badges):
    flux = BytesIO()
    document = canvas.Canvas(flux, pagesize=A4, pageCompression=1)
    largeur_page, hauteur_page = A4
    marge_y, ecart_x, ecart_y = 18, 12, 10
    colonnes, rangees = 2, 4
    images = {}
    for type_badge, nom_image in (
        (BadgeGenere.Type.APPRENANT, "badgeApprenant.png"),
        (BadgeGenere.Type.ENSEIGNANT, "badgeEnseignant.png"),
    ):
        chemin = finders.find(f"images/{nom_image}")
        if chemin is None:
            raise FileNotFoundError(f"Image de modèle introuvable : {nom_image}")
        images[type_badge] = chemin

    enseignants = [badge.appartenance_id for badge in badges if badge.appartenance_id]
    affectations_par_enseignant = {}
    annee_active = None
    if enseignants:
        affectations = AffectationEnseignant.objects.filter(
            appartenance_id__in=enseignants,
            matiere_niveau__annee__statut=AnneeAcademique.Statut.ACTIVE,
        ).select_related(
            "matiere_niveau__matiere", "matiere_niveau__niveau__programme__faculte",
        )
        for affectation in affectations:
            affectations_par_enseignant.setdefault(affectation.appartenance_id, []).append(affectation)
        annee_active = AnneeAcademique.objects.filter(
            etablissement=etablissement, statut=AnneeAcademique.Statut.ACTIVE,
        ).first()

    espace_total = colonnes * LARGEUR_CARTE + (colonnes - 1) * ecart_x
    origine_x = (largeur_page - espace_total) / 2

    for index, badge in enumerate(badges):
        position = index % (colonnes * rangees)
        colonne, rangee = position % colonnes, position // colonnes
        x = origine_x + colonne * (LARGEUR_CARTE + ecart_x)
        y = hauteur_page - marge_y - HAUTEUR_CARTE - rangee * (HAUTEUR_CARTE + ecart_y)
        _dessiner_badge_modele(
            document, etablissement, badge, x, y, images,
            affectations_par_enseignant, annee_active,
        )
        if position == colonnes * rangees - 1 or index == len(badges) - 1:
            document.showPage()

    document.save()
    return flux.getvalue()


@transaction.atomic
def generer_badges(etablissement, cibles, par):
    """Génère un PDF multi-badges et conserve les jetons de vérification."""
    if not cibles:
        raise ErreurMetier("Aucun apprenant ou enseignant à inclure dans les badges.")

    badges = []
    for type_badge, cible in cibles:
        if cible.etablissement_id != etablissement.pk:
            raise ErreurMetier("Un badge ne peut viser qu'une personne du même établissement.")
        if type_badge == BadgeGenere.Type.APPRENANT:
            if cible.statut != cible.Statut.VALIDEE:
                raise ErreurMetier("Les badges ne peuvent être créés que pour les inscriptions validées.")
            badges.append(BadgeGenere.sans_filtre.create(
                etablissement=etablissement, type_badge=type_badge,
                inscription=cible, classe=cible.classe, genere_par=par,
            ))
        elif type_badge == BadgeGenere.Type.ENSEIGNANT:
            if not cible.actif or cible.role.nom != "Enseignant":
                raise ErreurMetier("Le badge sélectionné ne correspond pas à une appartenance d'enseignant active.")
            badges.append(BadgeGenere.sans_filtre.create(
                etablissement=etablissement, type_badge=type_badge,
                appartenance=cible, genere_par=par,
            ))
        else:
            raise ErreurMetier("Type de badge invalide.")

    pdf = _creer_pdf(etablissement, badges)
    enregistrer_audit(
        etablissement, par, "badge.generation", badges[0],
        apres={"nombre": len(badges), "types": sorted({badge.type_badge for badge in badges})},
    )
    return pdf
