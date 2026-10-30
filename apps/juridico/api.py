"""API de entrada do n8n (D-048): POST /api/juridico/recebimentos/ com a lista de itens em JSON.

Autenticação: `Authorization: Bearer <chave>` (ou `X-Api-Key`), a chave gerada na Configuração do
cadastro. Corpo: a lista de itens, {"itens": [...]} ou o envelope do n8n com "registros" (sozinho
ou em lista, D-059); até 500 itens e 2 MB.

Respostas (sempre JSON): 200 {ok: true, lote, recebidos, novos, repetidos, invalidos: [{indice,
mensagem}]}; 400 JSON inválido ou formato errado; 401 chave ausente/errada; 405 método; 413
grande demais; 503 API sem chave configurada. Erro: {ok: false, erros: [{campo, mensagem}]}.

Todo POST, aceito ou recusado, vira uma linha em `ChamadaApi` (log do jurídico, D-049).
"""

import json
import logging
import time

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import recebimentos
from .models import ChamadaApi

logger = logging.getLogger(__name__)


def _erro(mensagem, status, campo=""):
    return JsonResponse(
        {"ok": False, "erros": [{"campo": campo, "mensagem": mensagem}]}, status=status
    )


def _tamanho(request):
    try:
        return max(int(request.META.get("CONTENT_LENGTH") or 0), 0)
    except ValueError:
        return 0


def _registrar_chamada(request, status, mensagem, resultado, inicio):
    """Uma linha no log; falha ao gravar o log nunca derruba a resposta da API."""
    resultado = resultado or {}
    try:
        ChamadaApi.objects.create(
            status_http=status,
            mensagem=mensagem[:300],
            ip=request.META.get("REMOTE_ADDR") or None,
            agente=request.headers.get("user-agent", "")[:200],
            tamanho=min(_tamanho(request), 2**31 - 1),
            duracao_ms=int((time.monotonic() - inicio) * 1000),
            lote=resultado.get("lote"),
            recebidos=resultado.get("recebidos", 0),
            novos=resultado.get("novos", 0),
            repetidos=resultado.get("repetidos", 0),
            invalidos=len(resultado.get("invalidos", [])),
        )
    except Exception:  # noqa: BLE001 - o log é acessório; a chamada já foi tratada
        logger.exception("API do n8n: não consegui gravar o log da chamada")


@method_decorator(csrf_exempt, name="dispatch")  # chamada de máquina, autenticada pela chave
class RecebimentosApiView(View):
    http_method_names = ["post"]

    def http_method_not_allowed(self, request, *args, **kwargs):
        resposta = _erro("Use POST.", 405)
        resposta["Allow"] = "POST"
        return resposta

    def post(self, request):
        inicio = time.monotonic()
        status, mensagem, resultado = self._tratar(request)
        _registrar_chamada(request, status, mensagem, resultado, inicio)
        if resultado is None:
            return _erro(mensagem, status, "itens" if status in (400, 413) else "")
        return JsonResponse({"ok": True, **resultado})

    def _tratar(self, request):
        """(status HTTP, mensagem, resultado | None)."""
        confere = recebimentos.chave_confere(recebimentos.chave_do_pedido(request))
        if confere is None:
            return 503, "A API ainda não tem chave: gere uma na Configuração do cadastro.", None
        if not confere:
            logger.warning("API do n8n: chave recusada (%s)", request.META.get("REMOTE_ADDR"))
            return 401, "Chave da API ausente ou inválida.", None
        if _tamanho(request) > recebimentos.MAX_BYTES or len(request.body) > recebimentos.MAX_BYTES:
            return 413, "Corpo maior que 2 MB: divida o envio.", None
        try:
            corpo = json.loads(request.body or b"null")
        except ValueError:
            return 400, "O corpo não é um JSON válido.", None
        itens = recebimentos.extrair_itens(corpo)
        if itens is None:
            return (
                400,
                'Envie uma lista de itens, {"itens": [...]} ou o envelope com "registros".',
                None,
            )
        if len(itens) > recebimentos.MAX_ITENS:
            return 413, f"No máximo {recebimentos.MAX_ITENS} itens por envio.", None
        resultado = recebimentos.registrar(itens)
        logger.info(
            "API do n8n: lote %s com %s itens (%s novos)",
            resultado["lote"], resultado["recebidos"], resultado["novos"],
        )  # fmt: skip
        mensagem = (
            f"{resultado['novos']} novo(s), {resultado['repetidos']} repetido(s), "
            f"{len(resultado['invalidos'])} inválido(s)."
        )
        return 200, mensagem, resultado
