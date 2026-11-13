from django.contrib import admin

from .models import Evenement, Publication

admin.site.register([Publication, Evenement])
