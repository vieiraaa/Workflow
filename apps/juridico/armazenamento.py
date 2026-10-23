"""Armazenamento privado dos PDFs (CAD-04): disco do servidor, nunca servido por URL."""

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class ArmazenamentoPrivado(FileSystemStorage):
    """`settings.MEDIA_ROOT` lido a cada uso (os testes trocam a pasta); sem URL pública."""

    @property
    def base_location(self):
        return str(settings.MEDIA_ROOT)

    @property
    def location(self):
        return str(settings.MEDIA_ROOT)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError("Os PDFs do cadastro só são baixados pela view juridico:pdf.")
