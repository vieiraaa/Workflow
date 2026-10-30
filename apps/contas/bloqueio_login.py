"""Bloqueio de tentativas no login pelo AD (D-039; fecha a lacuna da D-012), como no Monitor de IA:
5 erros seguidos no par IP + usuário bloqueiam 60 s; 20 erros do mesmo IP em 5 min bloqueiam o IP.
Também evita que alguém tranque a conta de rede de outra pessoa errando a senha. Estado no cache."""

import time

from django.core.cache import cache

MAX_FALHAS, BLOQUEIO_S = 5, 60
MAX_FALHAS_IP, JANELA_IP_S = 20, 300


def chave(request, login):
    ip = request.META.get("REMOTE_ADDR", "?") if request else "?"
    return ip, (login or "").lower()[:100]


def _k(par):
    return f"login:par:{par[0]}|{par[1]}"


def _recentes_ip(ip, agora):
    return [t for t in cache.get(f"login:ip:{ip}", []) if t > agora - JANELA_IP_S]


def espera(par):
    """Segundos de espera (0 = liberado)."""
    agora = time.time()
    _, ate = cache.get(_k(par), (0, 0))
    segundos = int(ate - agora) + 1 if ate > agora else 0
    recentes = _recentes_ip(par[0], agora)
    if len(recentes) >= MAX_FALHAS_IP:
        segundos = max(segundos, int(recentes[0] + JANELA_IP_S - agora) + 1)
    return segundos


def registrar_falha(par):
    agora = time.time()
    n, ate = cache.get(_k(par), (0, 0))
    n = 1 if ate and ate < agora else n + 1
    cache.set(_k(par), (n, agora + BLOQUEIO_S if n >= MAX_FALHAS else 0), JANELA_IP_S)
    cache.set(f"login:ip:{par[0]}", [*_recentes_ip(par[0], agora), agora], JANELA_IP_S)


def limpar(par):
    cache.delete(_k(par))
