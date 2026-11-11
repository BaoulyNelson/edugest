"""Gestionnaires des pages d'erreur publiques."""
from django.shortcuts import render


def page_introuvable(request, exception):
    return render(request, "404.html", status=404)
