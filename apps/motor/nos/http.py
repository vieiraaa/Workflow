"""Nó Requisição HTTP v2 (NOV-05, MV2-12 L1, MV2-15 B6/B7, MV2-16, CRD-02).

Uma requisição por item de entrada (com paginação opcional). O item de saída é o CORPO da resposta
(lista → 1 item por elemento; objeto → 1 item; texto → {"data": texto}); com `resposta_completa`
é {status, headers, corpo}. A credencial escolhida pelo nome injeta o header; o valor nunca vai
para o grafo, o histórico, as mensagens ou o log (mascarado por nome e por VALOR).
"""

import json
import time
from urllib.parse import quote, urlencode

from apps.credenciais.models import Credencial

from .. import credenciais, mascarar
from .. import http as cliente
from ..erros import FalhaNo
from ..expressoes import avaliar, como_texto, resolver_texto, resolver_valor
from . import LIMITE_ITENS, tipo
from .base import por_item

MAX_REQUISICOES_REGISTRADAS = 100
TIPOS_DE_CREDENCIAL = (Credencial.BEARER, Credencial.HEADER, Credencial.BASIC)


def _sem_quebra(valor):
    if "\r" in valor or "\n" in valor:
        raise FalhaNo(
            "placeholder", "O valor contém quebra de linha e não pode ir em cabeçalho ou parâmetro."
        )
    return valor


def _json_como_conteudo(valor):
    return json.dumps(valor, ensure_ascii=False)[1:-1]


def _url(texto, escopo):
    if texto.startswith("="):
        texto = texto[1:]
    if texto.startswith("{{") and not texto.startswith("{{{"):
        fim = texto.find("}}")
        if fim != -1:  # MV2-19: expressão no início fornece esquema/host e entra como está
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


def _expressao_unica(conteudo):
    texto = conteudo.strip()
    return texto.startswith("=") or (
        texto.startswith("{{") and texto.endswith("}}") and texto.count("{{") == 1
    )


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
    if _expressao_unica(conteudo):
        texto = json.dumps(resolver_valor(conteudo, escopo), ensure_ascii=False, allow_nan=False)
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


# ---------------------------------------------------------------- resposta → itens
def _conteudo_da_resposta(resposta, modo):
    if modo == "texto":
        return resposta.get("texto", "")
    if modo == "json":
        try:
            return json.loads(resposta.get("texto", ""))
        except ValueError, RecursionError:
            raise FalhaNo("json_invalido", "A resposta não é um JSON válido.") from None
    return resposta["corpo"]


def itens_da_resposta(resposta, config):
    modo = config.get("resposta", "automatica")
    corpo = _conteudo_da_resposta(resposta, modo)
    if config.get("resposta_completa") is True:
        itens = [
            {"json": {"status": resposta["status"], "headers": resposta["headers"], "corpo": corpo}}
        ]
    elif modo != "texto" and isinstance(corpo, list):
        itens = [{"json": el if isinstance(el, dict) else {"data": el}} for el in corpo]
    elif modo != "texto" and isinstance(corpo, dict):
        itens = [{"json": corpo}]
    else:
        itens = [{"json": {"data": corpo}}]
    if resposta.get("truncado"):  # corpo cortado no limite: o histórico marca "truncado"
        for item in itens:
            item["truncado"] = True
    return itens


def _vazia(resposta):
    corpo = resposta["corpo"]
    return corpo in ([], {}, None) or (isinstance(corpo, str) and not corpo.strip())


# ---------------------------------------------------------------- credencial
def _cabecalho_da_credencial(ctx, config):
    nome = config.get("credencial")
    if not nome:
        return None
    tipo_cred, dados = credenciais.carregar(nome, ctx.setor_id, TIPOS_DE_CREDENCIAL)
    cabecalho, valor, segredos = credenciais.cabecalho_http(tipo_cred, dados)
    ctx.adicionar_segredos(segredos)
    return {"nome": cabecalho, "valor": valor}


# ---------------------------------------------------------------- requisição
MAX_CORPO_GRAVADO = 8 * 1024


def _resposta_gravavel(resposta):
    """Resposta a gravar no histórico (MV2-22, EXE-06): status, headers, corpo ≤ 8 KB e `truncado`.
    O mascaramento (SEG-09 por nome, SEG-18 por valor) é feito pelo executor ao gravar."""
    bruto = resposta.get("texto", "").encode("utf-8")
    return {
        "status": resposta["status"],
        "headers": dict(resposta["headers"]),
        "corpo": bruto[:MAX_CORPO_GRAVADO].decode("utf-8", errors="ignore"),
        "truncado": len(bruto) > MAX_CORPO_GRAVADO or bool(resposta.get("truncado")),
    }


def _enviar(ctx, resolvido, cabecalho, requisicoes):
    """Faz UMA requisição (uma página). Devolve a resposta; 4xx/5xx saem como `FalhaNo`."""
    enviado = dict(resolvido)
    if cabecalho:
        outros = [h for h in enviado["headers"] if h["nome"].lower() != cabecalho["nome"].lower()]
        enviado["headers"] = [*outros, cabecalho]
    ctx.adicionar_segredos(mascarar.valores_sensiveis_da_requisicao(enviado))
    registro = ctx.mascarar_requisicao(enviado)
    if len(requisicoes) < MAX_REQUISICOES_REGISTRADAS:
        requisicoes.append(registro)
    restante = ctx.prazo_restante()
    if restante <= 0:
        raise FalhaNo("timeout", cliente.MENSAGENS["timeout"], requisicao=registro)
    try:
        resposta = cliente.requisitar(prazo_s=restante, **enviado)
    except cliente.ErroHttp as erro:
        raise FalhaNo(erro.categoria, erro.mensagem, requisicao=registro) from None
    ctx.segredos |= mascarar.valores_sensiveis(resposta["headers"])
    registro["status"] = resposta["status"]
    registro["resposta"] = _resposta_gravavel(resposta)
    resposta["_registro"] = registro
    return resposta


def _conferir_status(resposta):
    categoria = cliente.categoria_de_status(resposta["status"])
    if categoria:
        mensagem = f"{cliente.MENSAGENS[categoria]} (HTTP {resposta['status']})"
        raise FalhaNo(
            categoria,
            mensagem,
            saida=mascarar.mascarar_saida_http(resposta),
            requisicao=resposta["_registro"],
        )


# ---------------------------------------------------------------- paginação
def _expressao(texto, escopo):
    """Campo de expressão da paginação: `{{ }}`/`=...` como template; `$...` como expressão nua."""
    if "{{" in texto or texto.startswith("="):
        return resolver_valor(texto, escopo)
    if texto.strip().startswith("$"):
        return avaliar(texto.strip(), escopo)
    return texto


def _definir_no_caminho(objeto, caminho, valor):
    partes = [p for p in caminho.split(".") if p]
    if not partes:
        raise FalhaNo("paginacao", "O nome do campo de paginação está vazio.")
    for parte in partes[:-1]:
        proximo = objeto.get(parte)
        if not isinstance(proximo, dict):
            proximo = objeto[parte] = {}
        objeto = proximo
    objeto[partes[-1]] = valor


def _aplicar_parametro(resolvido, paginacao, valor):
    onde, nome = paginacao.get("onde", "query"), paginacao.get("nome", "")
    if onde in ("query", "header"):
        lista = resolvido["query" if onde == "query" else "headers"]
        texto = _sem_quebra(como_texto(valor))
        for par in lista:
            if par["nome"] == nome:
                par["valor"] = texto
                break
        else:
            lista.append({"nome": nome, "valor": texto})
        return
    try:
        corpo = json.loads(resolvido["corpo"]) if resolvido["corpo"].strip() else {}
    except ValueError:
        raise FalhaNo("paginacao", "O corpo não é um JSON válido para a paginação.") from None
    if not isinstance(corpo, dict):
        raise FalhaNo("paginacao", "O corpo precisa ser um objeto JSON para a paginação.")
    _definir_no_caminho(corpo, nome, valor)
    resolvido["corpo"] = json.dumps(corpo, ensure_ascii=False, allow_nan=False)


def _paginar(ctx, config, item, indice, entrada, cabecalho, requisicoes):
    paginacao = config["paginacao"]
    limite = max(1, min(int(paginacao.get("limite_paginas", 10)), 100))
    intervalo = max(0, min(int(paginacao.get("intervalo_ms", 0)), 5000)) / 1000
    parar = paginacao.get("parar_quando", "resposta_vazia")
    total, buscadas, proximo = [], 0, None
    while True:
        escopo = ctx.escopo(item, indice, entrada, pagina=buscadas)
        resolvido = _resolver(config, escopo)
        if proximo is not None:
            if paginacao.get("modo") == "proxima_url":
                resolvido["url"] = proximo
            else:
                _aplicar_parametro(resolvido, paginacao, proximo)
        resposta = _enviar(ctx, resolvido, cabecalho, requisicoes)
        buscadas += 1
        if parar == "status" and resposta["status"] in (paginacao.get("codigos") or []):
            break
        _conferir_status(resposta)
        visao = {
            "status": resposta["status"],
            "headers": resposta["headers"],
            "body": resposta["corpo"],
        }
        escopo_resposta = ctx.escopo(item, indice, entrada, pagina=buscadas, resposta=visao)
        if parar == "resposta_vazia" and _vazia(resposta):
            break
        total.extend(itens_da_resposta(resposta, config))
        if len(total) > LIMITE_ITENS:
            raise FalhaNo("limite_itens", "O nó passou de 10.000 itens na saída.")
        if parar == "expressao" and _verdadeiro(
            _expressao(paginacao.get("expressao", ""), escopo_resposta)
        ):
            break
        if buscadas >= limite:
            break  # limite de páginas: para sem erro (MV2-15 B7)
        if paginacao.get("modo") == "proxima_url":
            proximo = _expressao(paginacao.get("url", ""), escopo_resposta)
            if not proximo or not isinstance(proximo, str):
                break
        else:
            proximo = _expressao(paginacao.get("valor", ""), escopo_resposta)
        if intervalo:
            time.sleep(intervalo)
    return total


def _verdadeiro(valor):
    return bool(valor) and valor not in ("false", "0")


@tipo("http")
def executar(ctx, no, entradas):
    config = no["config"]
    cabecalho = _cabecalho_da_credencial(ctx, config)
    requisicoes = []

    def uma(item, indice, escopo):
        if config.get("paginacao"):
            return _paginar(ctx, config, item, indice, entradas[0], cabecalho, requisicoes)
        resposta = _enviar(ctx, _resolver(config, escopo), cabecalho, requisicoes)
        _conferir_status(resposta)
        return itens_da_resposta(resposta, config)

    resultado = por_item(ctx, no, entradas[0], uma)
    resultado.requisicoes = requisicoes
    return resultado
