"""Mascaramento de segredos no que é gravado e exibido (SEG-09).

Headers e parâmetros de query sensíveis aparecem como `••••`: Authorization,
Proxy-Authorization, Cookie, Set-Cookie, X-Api-Key e qualquer nome que contenha token, secret,
senha, password ou api-key (sem diferenciar maiúsculas).
"""

import json
import re
from urllib.parse import quote, unquote_plus

MASCARA = "••••"
NOMES_EXATOS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
TRECHOS = ("token", "secret", "senha", "password", "api-key", "api_key", "apikey")
_QUERY_NA_URL = re.compile(r"([?&])([^=&#]*)(=)([^&#]*)")


def sensivel(nome, decodificar=False):
    """`decodificar=True` compara o nome após percent-decode (nomes de query dentro de URLs)."""
    nome = unquote_plus(str(nome)) if decodificar else str(nome)
    minusculo = nome.strip().lower()
    return minusculo in NOMES_EXATOS or any(trecho in minusculo for trecho in TRECHOS)


def _nome_incerto(nome):
    """Nome ainda com placeholder (`{{ ... }}`): só se sabe qual é na execução."""
    return "{{" in str(nome)


def mascarar_pares(pares, estatico=False):
    """Lista [{nome, valor}] (headers/query de entrada) com os valores sensíveis mascarados.

    `estatico=True` (grafo ainda não resolvido): nome com placeholder também é mascarado, pois
    pode resolver para um nome sensível.
    """
    return [
        {**par, "valor": MASCARA}
        if sensivel(par.get("nome", "")) or (estatico and _nome_incerto(par.get("nome", "")))
        else dict(par)
        for par in pares or []
    ]


def mascarar_headers_dict(headers):
    """Dict {nome: valor} (headers de resposta) com os valores sensíveis mascarados."""
    return {nome: (MASCARA if sensivel(nome) else valor) for nome, valor in (headers or {}).items()}


def mascarar_url(url):
    """Mascara o valor de parâmetros de query sensíveis dentro da própria URL."""

    def trocar(achado):
        sep, nome, igual, valor = achado.groups()
        return f"{sep}{nome}{igual}{MASCARA if sensivel(nome, decodificar=True) else valor}"

    return _QUERY_NA_URL.sub(trocar, url) if isinstance(url, str) else url


def mascarar_entrada_http(entrada, estatico=False):
    """Entrada gravada de um nó http (EXE-12): url, headers e query mascarados."""
    mascarada = dict(entrada)
    if "url" in mascarada:
        mascarada["url"] = mascarar_url(mascarada["url"])
    for campo in ("headers", "query"):
        if campo in mascarada:
            mascarada[campo] = mascarar_pares(mascarada[campo], estatico)
    return mascarada


def valores_sensiveis(headers):
    """Valores (inteiros e em pedaços de cookie) de headers sensíveis de uma resposta.

    Servem para mascarar, na entrada gravada do nó seguinte, o que um placeholder copiou deles.
    """
    achados = set()
    for nome, valor in (headers or {}).items():
        if not sensivel(nome) or not isinstance(valor, str):
            continue
        achados.add(valor)
        for parte in re.split(r", |; ", valor):
            achados.add(parte)
            achados.add(parte.partition("=")[2])
    return {a for a in achados if len(a) >= 4}


def ocultar_valores(entrada, segredos):
    """Troca por `••••` qualquer ocorrência dos `segredos` (crus, JSON-escapados ou percent-encoded)
    no texto de url, nomes e valores de headers/query e corpo da entrada gravada."""
    if not segredos:
        return entrada
    variantes = set()
    for segredo in segredos:
        variantes |= {
            segredo,
            json.dumps(segredo, ensure_ascii=False)[1:-1],
            quote(segredo, safe=""),
        }
    ordenadas = sorted((v for v in variantes if v), key=len, reverse=True)

    def limpar(texto):
        for variante in ordenadas:
            texto = texto.replace(variante, MASCARA)
        return texto

    resultado = dict(entrada)
    for campo in ("url", "corpo"):
        if isinstance(resultado.get(campo), str):
            resultado[campo] = limpar(resultado[campo])
    for campo in ("headers", "query"):
        resultado[campo] = [
            {"nome": limpar(par["nome"]), "valor": limpar(par["valor"])}
            for par in resultado.get(campo) or []
        ]
    return resultado


def mascarar_saida_http(saida):
    """Saída gravada de um nó http (EXE-12): headers de resposta mascarados."""
    mascarada = dict(saida)
    if "headers" in mascarada:
        mascarada["headers"] = mascarar_headers_dict(mascarada["headers"])
    return mascarada


def mascarar_grafo(grafo):
    """Cópia do grafo canônico com headers/query sensíveis dos nós http mascarados (SEG-16.5)."""
    copia = json.loads(json.dumps(grafo))
    for no in copia.get("nos", []):
        if no.get("tipo") == "http" and isinstance(no.get("config"), dict):
            no["config"] = mascarar_entrada_http(no["config"], estatico=True)
    return copia


class FiltroMascararQuery:
    """Filtro de logging: mascara query sensível (`?token=…`) na mensagem e nos argumentos."""

    def filter(self, registro):
        registro.msg = (
            mascarar_url(registro.getMessage()) if registro.args else mascarar_url(registro.msg)
        )
        registro.args = None
        return True
