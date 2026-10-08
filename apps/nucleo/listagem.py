"""Utilidades comuns das listagens: página válida e querystring dos filtros."""

from urllib.parse import urlencode

POR_PAGINA = 25


def pagina_valida(paginator, valor):
    """Página pedida: inválida/menor que 1 → 1; acima do total → a última."""
    try:
        numero = int(valor)
    except TypeError, ValueError:
        numero = 1
    return paginator.get_page(min(max(numero, 1), paginator.num_pages))


def consulta(parametros, padroes=None, **trocas):
    """Querystring (sem '?') com os parâmetros não vazios e diferentes do padrão."""
    padroes = padroes or {}
    valores = {**parametros, **trocas}
    itens = [(k, v) for k, v in valores.items() if v and padroes.get(k) != v]
    return urlencode(itens)
