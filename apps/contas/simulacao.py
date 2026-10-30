"""Simular usuário (D-047): o Adm vê o produto como outra pessoa, só para leitura.

A sessão guarda o id do usuário simulado. A cada requisição o middleware confere pelo motor que
quem está logado ainda pode simular e que o alvo segue ativo, e troca `request.user` pelo alvo
só durante a view (`request.usuario_real` guarda o Adm). Mutação (POST, PUT, PATCH, DELETE) é
recusada, exceto encerrar a simulação e sair. Presença e último login seguem com o Adm.
"""

import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .permissoes import pode

CHAVE_SESSAO = "simulando_usuario_id"
ROTAS_LIVRES = {"contas:simulacao_encerrar", "logout"}  # rodam como o Adm, sem a troca
METODOS_LEITURA = {"GET", "HEAD", "OPTIONS"}
MENSAGEM_SO_LEITURA = "A simulação é só para leitura: encerre-a para fazer alterações."

logger = logging.getLogger(__name__)


def pode_simular(adm, alvo):
    return pode(adm, "usuarios.simular") and alvo.is_active and alvo.pk != adm.pk


def iniciar(request, alvo):
    request.session[CHAVE_SESSAO] = alvo.pk
    logger.info("Simulação iniciada: %s vendo como %s", request.user.email, alvo.email)


def encerrar(request):
    """Tira a simulação da sessão. Devolve True se havia uma."""
    alvo_id = request.session.pop(CHAVE_SESSAO, None)
    if alvo_id is not None:
        logger.info("Simulação encerrada: %s (alvo id %s)", request.user.email, alvo_id)
    return alvo_id is not None


def _alvo(request):
    """Usuário simulado desta requisição, ou None (e a simulação inválida sai da sessão)."""
    if CHAVE_SESSAO not in request.session or not request.user.is_authenticated:
        return None
    from .models import Usuario

    alvo = Usuario.objects.filter(pk=request.session[CHAVE_SESSAO]).first()
    if alvo is None or not pode_simular(request.user, alvo):
        encerrar(request)
        return None
    return alvo


def _quer_json(request):
    return (
        request.content_type == "application/json"
        or "application/json" in request.headers.get("accept", "")
        or request.headers.get("x-requested-with", "").lower() in ("fetch", "xmlhttprequest")
    )


def _recusar(request):
    if _quer_json(request):
        erro = {"campo": "", "mensagem": MENSAGEM_SO_LEITURA}
        return JsonResponse({"ok": False, "erros": [erro]}, status=403)
    messages.warning(request, MENSAGEM_SO_LEITURA)
    volta = request.headers.get("referer", "")
    if not url_has_allowed_host_and_scheme(
        volta, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        volta = reverse("inicio")
    return redirect(volta)


class SimulacaoMiddleware:
    """Depois do AuthenticationMiddleware e do MessageMiddleware (usa `messages`)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        alvo = _alvo(request)
        if alvo is None:
            return self.get_response(request)
        try:
            rota = resolve(request.path_info).view_name
        except Resolver404:
            rota = ""
        if rota in ROTAS_LIVRES:
            return self.get_response(request)
        if request.method not in METODOS_LEITURA:
            return _recusar(request)
        real = request.user
        request.usuario_real = real
        request.user = alvo
        try:
            return self.get_response(request)
        finally:
            request.user = real  # presença (middleware de fora) e logs ficam com o Adm
