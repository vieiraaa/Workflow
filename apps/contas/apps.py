from django.apps import AppConfig


class ContasConfig(AppConfig):
    name = "apps.contas"

    def ready(self):
        from . import presenca  # noqa: F401  (registra o sinal de logout da presença)
