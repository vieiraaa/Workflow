"""Nó Requisição HTTP v2 (NOV-05, MV2-12 L1): uma requisição por item de entrada."""

import json
from urllib.parse import quote, urlencode

from .. import http as cliente
from .. import mascarar
from ..erros import FalhaNo
from ..expressoes import ErroExpressao, resolver_texto, resolver_valor
from . import tipo
from .base import por_item


def _sem_quebra(valor):
    if "\r" in valor or "\n" in valor:
        raise ErroExpressao(
            "O valor contém quebra de linha e não pode ir em cabeçalho ou parâmetro."
        )
    return valor


def _json_como_conteudo(valor):
    return json.dumps(valor, ensure_ascii=False)[1:-1]


def _url(texto, escopo):
    if texto.startswith("{{") and not texto.startswith("{{{"):
        fim = texto.find("}}")
        if fim != -1:  # expressão no início fornece esquema/host: entra como está
            inicio = resolver_texto(texto[: fim + 2], escopo, _sem_quebra)
            return inicio + resolver_texto(texto[fim + 2 :], escopo, lambda v: quote(v, safe=""))
    return resolver_texto(texto, escopo, lambda v: quote(v, safe=""))


def _pares(pares, escopo):
    return [
        {
            "nome": resolver_texto(p["nome"], escopo, _sem_quebra),
            "valor": resolver_texto(p["valor"], escopo, _sem_quebra),
        }
        for p in pares or []
    ]


def _corpo(corpo, escopo):
    """(texto do corpo, content-type padrão ou None)."""
    tipo_corpo, conteudo = corpo.get("tipo", "nenhum"), corpo.get("conteudo", "")
    if tipo_corpo == "formulario":
        pares = _pares(conteudo, escopo)
        if not pares:
            return "", None
        texto = urlencode([(p["nome"], p["valor"]) for p in pares], quote_via=quote)
        return texto, "application/x-www-form-urlencoded"
    if tipo_corpo == "nenhum" or not conteudo.strip():
        return "", None
    if tipo_corpo == "texto":
        return resolver_texto(conteudo, escopo), "text/plain; charset=utf-8"
    valor = (
        resolver_valor(conteudo, escopo)
        if conteudo.lstrip().startswith("=")
        or (
            conteudo.strip().startswith("{{")
            and conteudo.strip().endswith("}}")
            and conteudo.count("{{") == 1
        )
        else None
    )
    if valor is not None:
        texto = json.dumps(valor, ensure_ascii=False, allow_nan=False)
    else:
        texto = resolver_texto(conteudo, escopo, _json_como_conteudo)
    try:
        json.loads(texto)
    except ValueError, RecursionError:
        raise FalhaNo("json_invalido", "O corpo resolvido não é um JSON válido.") from None
    return texto, None


def _resolver(config, escopo):
    corpo_texto, content_type = _corpo(config.get("corpo") or {}, escopo)
    headers = _pares(config.get("headers"), escopo)
    if content_type and not any(h["nome"].strip().lower() == "content-type" for h in headers):
        headers.append({"nome": "Content-Type", "valor": content_type})
    return {
        "metodo": config.get("metodo", "GET"),
        "url": _url(config.get("url", ""), escopo),
        "headers": headers,
        "query": _pares(config.get("query"), escopo),
        "corpo": corpo_texto,
    }


def itens_da_resposta(resposta, completa):
    itens = _itens(resposta, completa)
    if resposta.get("truncado"):  # corpo cortado no limite: o histórico marca "truncado"
        for item in itens:
            item["truncado"] = True
    return itens


def _itens(resposta, completa):
    corpo = resposta["corpo"]
    if completa:
        return [
            {
                "json": {
                    "status": resposta["status"],
                    "headers": resposta["headers"],
                    "corpo": corpo,
                }
            }
        ]
    if isinstance(corpo, list):
        return [{"json": el if isinstance(el, dict) else {"data": el}} for el in corpo]
    if isinstance(corpo, dict):
        return [{"json": corpo}]
    return [{"json": {"data": corpo}}]


@tipo("http")
def executar(ctx, no, entradas):
    config = no["config"]
    requisicoes = []

    def uma(item, indice, escopo):
        resolvido = _resolver(config, escopo)
        registro = ctx.mascarar_requisicao(resolvido)
        requisicoes.append(registro)
        restante = ctx.prazo_restante()
        if restante <= 0:
            raise FalhaNo("timeout", cliente.MENSAGENS["timeout"], requisicao=registro)
        try:
            resposta = cliente.requisitar(prazo_s=restante, **resolvido)
        except cliente.ErroHttp as erro:
            raise FalhaNo(erro.categoria, erro.mensagem, requisicao=registro) from None
        ctx.segredos |= mascarar.valores_sensiveis(resposta["headers"])
        registro["status"] = resposta["status"]
        categoria = cliente.categoria_de_status(resposta["status"])
        if categoria:
            mensagem = f"{cliente.MENSAGENS[categoria]} (HTTP {resposta['status']})"
            raise FalhaNo(
                categoria,
                mensagem,
                saida=mascarar.mascarar_saida_http(resposta),
                requisicao=registro,
            )
        return itens_da_resposta(resposta, config.get("resposta_completa") is True)

    resultado = por_item(ctx, no, entradas[0], uma)
    resultado.requisicoes = requisicoes
    return resultado
