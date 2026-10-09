"""Condições (NOV-02, MV2-15 B8) e os nós Se, Filtrar e Escolher."""

from datetime import datetime

from apps.fluxos import catalogo

from ..erros import FalhaNo
from ..expressoes import resolver_valor, tem_expressao
from ..expressoes.avaliador import para_numero
from . import tipo
from .base import rotear
from .regex import procurar
from .util import para_data


def _avaliar(texto, escopo):
    if isinstance(texto, str) and tem_expressao(texto):
        return resolver_valor(texto, escopo)
    return texto


def _vazio(valor):
    return valor is None or valor == "" or valor == [] or valor == {}


def _texto(valor):
    from ..expressoes import como_texto

    return "" if valor is None else como_texto(valor)


def _booleano(valor):
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "sim")
    return bool(valor)


def _normalizar(valor, tipo_valor):
    if tipo_valor == "texto":
        return _texto(valor)
    if tipo_valor == "numero":
        numero = para_numero(valor if valor is not None else "")
        return numero
    if tipo_valor == "booleano":
        return _booleano(valor)
    if tipo_valor == "data":
        return para_data(valor)
    if tipo_valor == "lista":
        return valor if isinstance(valor, list) else ([] if valor is None else [valor])
    return valor if isinstance(valor, dict) else {}


def _igual_solto(elemento, alvo):
    return elemento == alvo or _texto(elemento) == _texto(alvo)


def _comparar(operador, esquerda, direita):
    if operador == "igual":
        return esquerda == direita
    if operador == "diferente":
        return esquerda != direita
    try:
        if operador == "maior":
            return esquerda > direita
        if operador == "maior_igual":
            return esquerda >= direita
        if operador == "menor":
            return esquerda < direita
        return esquerda <= direita
    except TypeError:
        raise FalhaNo("expressao", "Valores incomparáveis na condição.") from None


def _uma(condicao, escopo):
    operador = condicao.get("operador")
    tipo_valor = condicao.get("tipo", "texto")
    bruto = _avaliar(condicao.get("esquerda", ""), escopo)
    if operador == "existe":
        return bruto is not None
    if operador == "nao_existe":
        return bruto is None
    if operador == "vazio":
        return _vazio(bruto)
    if operador == "nao_vazio":
        return not _vazio(bruto)
    direita_bruta = _avaliar(condicao.get("direita"), escopo)
    if operador == "regex":
        return procurar(_texto(direita_bruta), _texto(bruto))
    esquerda = _normalizar(bruto, tipo_valor)
    if operador in ("contem", "nao_contem"):
        if tipo_valor == "lista":
            achou = any(_igual_solto(e, direita_bruta) for e in esquerda)
        elif tipo_valor == "objeto":
            achou = _texto(direita_bruta) in esquerda
        else:
            achou = _texto(direita_bruta) in _texto(esquerda)
        return achou if operador == "contem" else not achou
    direita = _normalizar(direita_bruta, tipo_valor)
    if operador in ("comeca_com", "termina_com"):
        texto, alvo = _texto(esquerda), _texto(direita)
        return texto.startswith(alvo) if operador == "comeca_com" else texto.endswith(alvo)
    if tipo_valor in ("lista", "objeto") and operador not in ("igual", "diferente"):
        raise FalhaNo("expressao", "Operador inválido para este tipo de valor.")
    if isinstance(esquerda, datetime) or isinstance(direita, datetime):
        return _comparar(operador, esquerda, direita)
    return _comparar(operador, esquerda, direita)


def avaliar_condicoes(condicoes, combinar, escopo):
    resultados = (_uma(c, escopo) for c in condicoes)
    return all(resultados) if combinar != "ou" else any(resultados)


@tipo("se")
def se(ctx, no, entradas):
    config = no["config"]

    def decidir(item, indice, escopo):
        return (
            0
            if avaliar_condicoes(config.get("condicoes", []), config.get("combinar"), escopo)
            else 1
        )

    return rotear(ctx, no, entradas[0], decidir)


@tipo("filtrar")
def filtrar(ctx, no, entradas):
    config = no["config"]
    descartados = 1 if config.get("manter_descartados") is True else None

    def decidir(item, indice, escopo):
        ok = avaliar_condicoes(config.get("condicoes", []), config.get("combinar"), escopo)
        return 0 if ok else descartados

    return rotear(ctx, no, entradas[0], decidir)


@tipo("escolher")
def escolher(ctx, no, entradas):
    config = no["config"]
    regras = config.get("regras", [])
    outros = len(regras) if config.get("saida_outros") is True else None

    def decidir(item, indice, escopo):
        for posicao, regra in enumerate(regras):
            if avaliar_condicoes(regra.get("condicoes", []), regra.get("combinar"), escopo):
                return posicao
        return outros

    return rotear(ctx, no, entradas[0], decidir)


__all__ = ["avaliar_condicoes", "catalogo"]
