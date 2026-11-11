from io import BytesIO

from django.db import transaction
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from applications.noyau.exceptions import ErreurMetier
from applications.noyau.services import enregistrer_audit

from .models import BadgeGenere

LARGEUR_CARTE = 260
HAUTEUR_CARTE = 154


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


def _nom_cible(badge):
    if badge.type_badge == BadgeGenere.Type.APPRENANT:
        apprenant = badge.inscription.apprenant
        return apprenant.nom, apprenant.prenoms, apprenant.matricule
    utilisateur = badge.appartenance.utilisateur
    return utilisateur.last_name or utilisateur.username, utilisateur.first_name, utilisateur.email


def _creer_pdf(etablissement, badges):
    flux = BytesIO()
    document = canvas.Canvas(flux, pagesize=A4, pageCompression=1)
    largeur_page, hauteur_page = A4
    marge_x, marge_y, ecart_x, ecart_y = 32, 24, 12, 12
    colonnes, rangees = 2, 4
    espace_total = colonnes * LARGEUR_CARTE + (colonnes - 1) * ecart_x
    origine_x = (largeur_page - espace_total) / 2

    for index, badge in enumerate(badges):
        position = index % (colonnes * rangees)
        colonne, rangee = position % colonnes, position // colonnes
        x = origine_x + colonne * (LARGEUR_CARTE + ecart_x)
        y = hauteur_page - marge_y - HAUTEUR_CARTE - rangee * (HAUTEUR_CARTE + ecart_y)

        document.setFillColor(colors.HexColor("#f5f8fc"))
        document.setStrokeColor(colors.HexColor("#193b66"))
        document.roundRect(x, y, LARGEUR_CARTE, HAUTEUR_CARTE, 9, fill=1, stroke=1)
        document.setFillColor(colors.HexColor("#193b66"))
        document.rect(x, y + HAUTEUR_CARTE - 32, LARGEUR_CARTE, 32, fill=1, stroke=0)
        document.setFillColor(colors.white)
        document.setFont("Helvetica-Bold", 10)
        document.drawString(x + 12, y + HAUTEUR_CARTE - 20, etablissement.nom[:42])

        nom, prenoms, reference = _nom_cible(badge)
        document.setFillColor(colors.HexColor("#16283f"))
        document.setFont("Helvetica-Bold", 11)
        document.drawString(x + 12, y + HAUTEUR_CARTE - 58, f"{prenoms} {nom}".strip()[:30])
        document.setFont("Helvetica", 9)
        document.drawString(x + 12, y + HAUTEUR_CARTE - 76, reference[:34])
        document.setFillColor(colors.HexColor("#4c5c6e"))
        document.drawString(x + 12, y + 20, badge.get_type_badge_display())
        if badge.classe_id:
            document.drawString(x + 12, y + 36, f"Classe : {badge.classe.nom}"[:34])

        taille_qr = 76
        _dessiner_qr(document, str(badge.jeton), x + LARGEUR_CARTE - taille_qr - 12, y + 31, taille_qr)
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
