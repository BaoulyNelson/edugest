"""Exports Excel et PDF des résultats."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def exporter_excel(titre, entetes, lignes):
    classeur = Workbook()
    feuille = classeur.active
    feuille.title = titre[:31]
    feuille.append(entetes)
    for cellule in feuille[1]:
        cellule.font = Font(bold=True)
    for ligne in lignes:
        feuille.append(list(ligne))
    for colonne in feuille.columns:
        largeur = max(len(str(c.value or "")) for c in colonne) + 2
        feuille.column_dimensions[colonne[0].column_letter].width = min(largeur, 40)
    flux = BytesIO()
    classeur.save(flux)
    return flux.getvalue()


def exporter_pdf(titre, entetes, lignes):
    flux = BytesIO()
    document = SimpleDocTemplate(flux, pagesize=landscape(A4), title=titre, leftMargin=24, rightMargin=24)
    styles = getSampleStyleSheet()
    tableau = Table([entetes] + [list(map(str, ligne)) for ligne in lignes], repeatRows=1)
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f5c63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b9c4c6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6f6")]),
    ]))
    document.build([Paragraph(titre, styles["Title"]), Spacer(1, 12), tableau])
    return flux.getvalue()
