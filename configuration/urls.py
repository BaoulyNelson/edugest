"""Routes principales d'EduGest."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("administration/", admin.site.urls),
    path("", include("applications.comptes.urls")),
    path("", include("applications.noyau.urls")),
    path("academique/", include("applications.academique.urls")),
    path("apprenants/", include("applications.apprenants.urls")),
    path("pedagogie/", include("applications.pedagogie.urls")),
    path("evaluations/", include("applications.evaluations.urls")),
    path("finances/", include("applications.finances.urls")),
    path("presences/", include("applications.presences.urls")),
    path("cahier/", include("applications.cahier.urls")),
    path("messagerie/", include("applications.messagerie.urls")),
    path("emploi/", include("applications.emploi_du_temps.urls")),
    path("importations/", include("applications.importations.urls")),
    path("rgpd/", include("applications.rgpd.urls")),
    path("admissions/", include("applications.admissions.urls")),
    path("badges/", include("applications.badges.urls")),
]

handler404 = "configuration.erreurs.page_introuvable"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
