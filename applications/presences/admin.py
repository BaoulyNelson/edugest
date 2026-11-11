from django.contrib import admin

from .models import AppelPresence, LignePresence, NotificationPresence

admin.site.register([AppelPresence, LignePresence, NotificationPresence])
