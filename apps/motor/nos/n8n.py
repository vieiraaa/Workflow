"""Nó Chamar n8n (N8N-01..06): chama o Webhook de um fluxo do n8n SOBRE o cliente HTTP do motor.

Nenhum caminho de rede novo: URL, credencial, SSRF, mascaramento e limites são os do nó HTTP
(`nos/http.py` → `motor/http.py`). Só mudam o envio (corpo JSON do item), a leitura da resposta e
as mensagens de erro. O valor da credencial nunca vai para erro, log ou saída.
"""

import json

from ..erros import FalhaNo
from ..mascarar import mascarar_saida_http, ocultar_valores
from . import tipo
from . import http as nohttp
from .base import por_item

CORPO_SEM_ESPERA = 64 * 1024
TRECHO_ERRO = 200
USER_AGENT = "construtor-workflows/1.0"

MSG_404 = (
    "Webhook do n8n não encontrado: confira a URL e se o fluxo está ATIVO no n8n "
    "(ou em 'Listen for test event' na URL de teste)."
)
MSG_AUTENTICACAO = "O n8n recusou a autenticação: confira a credencial do webhook."


def _config(config):
    return {
        "metodo": config.get("metodo", "POST"),
        "enviar": config.get("enviar", "item"),
        "aguardar": config.get("aguardar_resposta", True),
        "tempo": config.get("tempo_limite_s", 30),
    }


def _query_escalares(dados):
    pares = []
    for nome, valor in dados.items():
        if isinstance(valor, bool):
            texto = "true" if valor else "false"
        elif isinstance(valor, int | float | str):
            texto = str(valor)
        else:
            continue  # nulo, lista e objeto não vão na query
        pares.append({"nome": nome, "valor": nohttp._sem_quebra(texto)})
    return pares


def _requisicao(config, opcoes, escopo, dados):
    """Requisição resolvida (mesmo formato do nó HTTP) para o JSON `dados`."""
    url = nohttp._url(config.get("url", ""), escopo)
    if opcoes["metodo"] == "GET":
        return {
            "metodo": "GET",
            "url": url,
            "headers": [{"nome": "User-Agent", "valor": USER_AGENT}],
            "query": _query_escalares(dados) if isinstance(dados, dict) else [],
            "corpo": "",
        }
    return {
        "metodo": "POST",
        "url": url,
        "headers": [
            {"nome": "Content-Type", "valor": "application/json"},
            {"nome": "User-Agent", "valor": USER_AGENT},
        ],
        "query": [],
        "corpo": json.dumps(dados, ensure_ascii=False, allow_nan=False),
    }


def _corpo_personalizado(config, escopo):
    texto, _ = nohttp._corpo({"tipo": "json", "conteudo": config.get("corpo", "")}, escopo)
    valor = json.loads(texto)
    if not isinstance(valor, dict | list):
        raise FalhaNo("json_invalido", "O corpo a enviar deve ser um objeto ou uma lista JSON.")
    return valor


# ---------------------------------------------------------------- erros e resposta
def _trecho(ctx, resposta):
    texto = ocultar_valores(
        {"corpo": resposta.get("texto", ""), "headers": [], "query": []}, ctx.segredos
    )["corpo"]
    texto = " ".join(texto.split())[:TRECHO_ERRO]
    return f" {texto}" if texto else ""


def _conferir(ctx, resposta):
    status = resposta["status"]
    if 200 <= status < 300:
        return
    if status == 404:
        mensagem = MSG_404
    elif status in (401, 403):
        mensagem = MSG_AUTENTICACAO
    else:
        mensagem = f"O n8n respondeu {status}.{_trecho(ctx, resposta)}"
    raise FalhaNo(
        "http_5xx" if status >= 500 else "http_4xx",
        mensagem,
        saida=mascarar_saida_http(resposta),
        requisicao=resposta["_registro"],
    )


def _item(valor):
    return {"json": valor} if isinstance(valor, dict) else {"json": {"valor": valor}}


def _itens_da_resposta(resposta):
    texto = resposta.get("texto", "")
    if not texto.strip():
        return [{"json": {"n8n_status": resposta["status"]}}]
    if resposta.get("truncado"):
        raise FalhaNo("resposta_grande", "A resposta do n8n passou do limite de 1 MB.")
    try:
        corpo = json.loads(texto)
    except ValueError, RecursionError:
        return [{"json": {"resposta": texto}}]
    if isinstance(corpo, list):
        return [_item(elemento) for elemento in corpo]
    return [_item(corpo)]


def _chamar(ctx, no, requisicao, opcoes, requisicoes, cabecalho):
    limites = {"prazo_max_s": opcoes["tempo"]}
    if not opcoes["aguardar"]:
        limites["corpo_max"] = CORPO_SEM_ESPERA
    try:
        resposta = nohttp._enviar(ctx, requisicao, cabecalho, requisicoes, **limites)
    except FalhaNo as falha:
        if falha.categoria == "timeout":
            raise FalhaNo(
                "timeout",
                f"O n8n não respondeu em {opcoes['tempo']} s. "
                "Para fluxos longos, use 'Não aguardar resposta' no nó.",
                requisicao=falha.requisicao,
            ) from None
        raise
    _conferir(ctx, resposta)
    return resposta


@tipo("chamar_n8n")
def executar(ctx, no, entradas):
    config = no["config"]
    opcoes = _config(config)
    cabecalho = nohttp._cabecalho_da_credencial(ctx, config)
    requisicoes = []
    todos = opcoes["enviar"] == "todos"
    itens = entradas[0]

    def saida(resposta, origem):
        if opcoes["aguardar"]:
            return _itens_da_resposta(resposta)
        status = resposta["status"]
        return [{"json": {**o["json"], "n8n_status": status}} for o in origem]

    def uma(item, indice, escopo):
        if todos:
            dados, origem = {"itens": [i["json"] for i in itens]}, itens
        elif opcoes["enviar"] == "personalizado":
            dados, origem = _corpo_personalizado(config, escopo), [item]
        else:
            dados, origem = item["json"], [item]
        requisicao = _requisicao(config, opcoes, escopo, dados)
        resposta = _chamar(ctx, no, requisicao, opcoes, requisicoes, cabecalho)
        return saida(resposta, origem)

    if todos and itens:
        resultado = por_item(ctx, no, [{"json": {"itens": [i["json"] for i in itens]}}], uma)
    elif todos:
        resultado = por_item(ctx, no, [], uma)
    else:
        resultado = por_item(ctx, no, itens, uma)
    resultado.requisicoes = requisicoes
    return resultado
