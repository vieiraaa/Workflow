"""Presença (D-041): "online" = alguma requisição nos últimos 5 min; ao sair, fica offline na hora.
Fica no cache, sem consulta ao banco por requisição. Com mais de um processo servindo a aplicação,
o cache precisa ser compartilhado (Redis ou banco); com um só (runserver, hoje), o padrão basta."""

import time
from datetime import UTC, datetime

from django.contrib.auth.signals import user_logged_out
from django.core.cache import cache
from django.dispatch import receiver

ONLINE_S = 300
GUARDA_S = 7 * 24 * 3600


def _chave(pk):
    return f"presenca:{pk}"


def registrar(usuario):
    cache.set(_chave(usuario.pk), time.time(), GUARDA_S)


def online(usuario):
    visto = cache.get(_chave(usuario.pk))
    return visto is not None and time.time() - visto < ONLINE_S


def visto_em(usuario):
    """Último sinal de vida: a última requisição (cache) ou, sem ela, o último login."""
    visto = cache.get(_chave(usuario.pk))
    return datetime.fromtimestamp(visto, UTC) if visto is not None else usuario.last_login


@receiver(user_logged_out)
def _saiu(sender, request, user, **kwargs):
    if user is not None:
        cache.delete(_chave(user.pk))


class PresencaMiddleware:
    """Marca o usuário logado como visto agora, depois da resposta."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resposta = self.get_response(request)
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            registrar(usuario)
        return resposta
