"""Mascaramento de segredos no que é gravado e exibido (SEG-09).

Headers e parâmetros de query sensíveis aparecem como `••••`: Authorization,
Proxy-Authorization, Cookie, Set-Cookie, X-Api-Key e qualquer nome que contenha token, secret,
senha, password ou api-key (sem diferenciar maiúsculas).
"""

import json
import re

MASCARA = "••••"
NOMES_EXATOS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
TRECHOS = ("token", "secret", "senha", "password", "api-key", "api_key", "apikey")
_QUERY_NA_URL = re.compile(r"([?&])([^=&#]*)(=)([^&#]*)")


def sensivel(nome):
    minusculo = str(nome).strip().lower()
    return minusculo in NOMES_EXATOS or any(trecho in minusculo for trecho in TRECHOS)


def mascarar_pares(pares):
    """Lista [{nome, valor}] (headers/query de entrada) com os valores sensíveis mascarados."""
    return [
        {**par, "valor": MASCARA} if sensivel(par.get("nome", "")) else dict(par)
        for par in pares or []
    ]


def mascarar_headers_dict(headers):
    """Dict {nome: valor} (headers de resposta) com os valores sensíveis mascarados."""
    return {nome: (MASCARA if sensivel(nome) else valor) for nome, valor in (headers or {}).items()}


def mascarar_url(url):
    """Mascara o valor de parâmetros de query sensíveis dentro da própria URL."""

    def trocar(achado):
        sep, nome, igual, valor = achado.groups()
        return f"{sep}{nome}{igual}{MASCARA if sensivel(nome) else valor}"

    return _QUERY_NA_URL.sub(trocar, url) if isinstance(url, str) else url


def mascarar_entrada_http(entrada):
    """Entrada gravada de um nó http (EXE-12): url, headers e query mascarados."""
    mascarada = dict(entrada)
    if "url" in mascarada:
        mascarada["url"] = mascarar_url(mascarada["url"])
    for campo in ("headers", "query"):
        if campo in mascarada:
            mascarada[campo] = mascarar_pares(mascarada[campo])
    return mascarada


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
            no["config"] = mascarar_entrada_http(no["config"])
    return copia
