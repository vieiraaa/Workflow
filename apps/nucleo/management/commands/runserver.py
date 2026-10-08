"""runserver do dev/demo: /static/ sempre com `Cache-Control: no-cache`.

O navegador revalida a cada carga (Last-Modified → 304 barato) e nunca reaproveita CSS/JS
antigo por heurística. Só vale onde `apps.nucleo` vem antes de `django.contrib.staticfiles` em
INSTALLED_APPS (dev.py e demo.py); produção usa collectstatic com hash e não passa por aqui.
"""

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.contrib.staticfiles.management.commands.runserver import Command as RunserverCommand


class StaticFilesSemCache(StaticFilesHandler):
    def serve(self, request):
        resposta = super().serve(request)
        resposta["Cache-Control"] = "no-cache"
        return resposta


class Command(RunserverCommand):
    def get_handler(self, *args, **options):
        handler = super().get_handler(*args, **options)
        if isinstance(handler, StaticFilesHandler):
            return StaticFilesSemCache(handler.application)
        return handler
