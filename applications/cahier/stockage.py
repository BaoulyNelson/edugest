import os
from functools import cached_property

from django.conf import settings
from django.core.files.storage import FileSystemStorage


EXTENSIONS_AUTORISEES = (
    "pdf", "doc", "docx", "odt", "ppt", "pptx", "xls", "xlsx",
    "png", "jpg", "jpeg", "gif", "webp",
)


class StockagePrive(FileSystemStorage):
    @cached_property
    def location(self):
        return os.fspath(settings.PRIVATE_MEDIA_ROOT)
