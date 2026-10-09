"""Nós de dados (NOV-03, MV2-15 B1/B2/B3/B9, MV2-17): Editar campos, Ordenar, Limitar, Remover
duplicados, Separar lista, Agregar, Resumir e Data e hora."""

import json
import math

from ..erros import FalhaNo
from ..expressoes import ErroExpressao, resolver_texto, resolver_valor, tem_expressao
from ..expressoes.avaliador import formatar_numero, normalizar_numero, para_numero
from ..expressoes.datas import Data, somar
from . import Resultado, tipo
from .base import conferir_limite, por_item
from .util import AUSENTE, copia, definir, obter, para_data, remover, ultimo_segmento


# ---------------------------------------------------------------- Editar campos
def _converter(valor, tipo_valor, nome):
    if tipo_valor == "texto":
        from ..expressoes import como_texto

        return "" if valor is None else como_texto(valor)
    if tipo_valor == "numero":
        numero = para_numero(valor if valor is not None else "")
        if isinstance(numero, float) and not math.isfinite(numero):
            return None
        return normalizar_numero(numero)
    if tipo_valor == "booleano":
        if isinstance(valor, str):
            return valor.strip().lower() in ("true", "1", "sim")
        return bool(valor)
    if tipo_valor == "lista":
        if isinstance(valor, str):
            valor = _json_ou_erro(valor, nome)
        if not isinstance(valor, list):
            raise FalhaNo("expressao", f"O campo '{nome}' precisa ser uma lista.")
        return valor
    if tipo_valor == "objeto":
        if isinstance(valor, str):
            valor = _json_ou_erro(valor, nome)
        if not isinstance(valor, dict):
            raise FalhaNo("expressao", f"O campo '{nome}' precisa ser um objeto.")
        return valor
    return valor


def _json_ou_erro(texto, nome):
    try:
        return json.loads(texto)
    except ValueError, RecursionError:
        raise FalhaNo("expressao", f"O campo '{nome}' não é um JSON válido.") from None


def _valor_do_campo(texto, escopo):
    return resolver_valor(texto, escopo) if tem_expressao(texto) else texto


@tipo("editar_campos")
def editar_campos(ctx, no, entradas):
    config = no["config"]
    incluir = config.get("incluir_outros") is True

    def uma(item, indice, escopo):
        base = copia(item["json"]) if incluir else {}
        if config.get("modo") == "json":
            texto = config.get("json", "")
            valor = resolver_valor(texto, escopo)
            if isinstance(valor, str):
                valor = _json_ou_erro(valor, "json")
            if not isinstance(valor, dict):
                raise FalhaNo("expressao", "O JSON do nó Editar campos precisa ser um objeto.")
            return [{"json": {**base, **copia(valor)}}]
        for campo in config.get("campos", []):
            nome = campo.get("nome", "")
            valor = _converter(
                _valor_do_campo(campo.get("valor", ""), escopo), campo.get("tipo", "texto"), nome
            )
            definir(base, nome, valor)
        return [{"json": base}]

    return por_item(ctx, no, entradas[0], uma)


# ---------------------------------------------------------------- Ordenar / Limitar / Duplicados
def _chave_de_ordem(valor):
    if valor is AUSENTE or valor is None:
        return (3, 0)
    if isinstance(valor, bool):
        return (1, int(valor))
    if isinstance(valor, int | float):
        return (0, valor)
    if isinstance(valor, str):
        return (2, valor)
    return (4, json.dumps(valor, sort_keys=True, ensure_ascii=False))


@tipo("ordenar")
def ordenar(ctx, no, entradas):
    itens = list(entradas[0])
    for campo in reversed(no["config"].get("campos", [])):  # estável: último critério primeiro
        caminho, desc = campo.get("campo", ""), campo.get("ordem", "asc") == "desc"
        itens.sort(key=lambda i: _chave_de_ordem(obter(i["json"], caminho)), reverse=desc)
    return Resultado(saidas=[itens])


@tipo("limitar")
def limitar(ctx, no, entradas):
    quantidade = max(int(no["config"].get("quantidade", 0)), 0)
    itens = entradas[0]
    recorte = (
        itens[-quantidade:]
        if no["config"].get("de") == "fim" and quantidade
        else itens[:quantidade]
    )
    if no["config"].get("de") == "fim" and quantidade == 0:
        recorte = []
    return Resultado(saidas=[list(recorte)])


def _impressao(valor):
    return json.dumps(None if valor is AUSENTE else valor, sort_keys=True, ensure_ascii=False)


@tipo("remover_duplicados")
def remover_duplicados(ctx, no, entradas):
    config = no["config"]
    campos = config.get("campos", []) if config.get("comparar") == "campos" else None
    vistos, saida = set(), []
    for item in entradas[0]:
        if campos is None:
            chave = _impressao(item["json"])
        else:
            chave = "|".join(_impressao(obter(item["json"], c)) for c in campos)
        if chave not in vistos:
            vistos.add(chave)
            saida.append(item)
    return Resultado(saidas=[saida])


# ---------------------------------------------------------------- Separar lista / Agregar / Resumir
@tipo("separar_lista")
def separar_lista(ctx, no, entradas):
    config = no["config"]
    caminho = config.get("campo", "")
    pai = config.get("incluir") == "campos_pai"

    def uma(item, indice, escopo):
        lista = obter(item["json"], caminho)
        if not isinstance(lista, list):
            raise FalhaNo("expressao", f"O campo '{caminho}' não existe ou não é uma lista.")
        base = {}
        if pai:
            base = copia(item["json"])
            remover(base, caminho)
        saida = []
        for elemento in lista:
            if isinstance(elemento, dict):
                saida.append({"json": {**base, **copia(elemento)}})
            else:
                saida.append({"json": {**base, ultimo_segmento(caminho): elemento}})
            if len(saida) > 10_000:
                raise FalhaNo("limite_itens", "O nó passou de 10.000 itens na saída.")
        return saida

    return por_item(ctx, no, entradas[0], uma)


@tipo("agregar")
def agregar(ctx, no, entradas):
    config = no["config"]
    itens = entradas[0]
    campos = config.get("campos", [])
    if config.get("modo") == "campos":
        if len(campos) == 1:
            nome = config.get("saida") or campos[0]
            json_saida = {nome: [_ou_nulo(obter(i["json"], campos[0])) for i in itens]}
        else:
            json_saida = {c: [_ou_nulo(obter(i["json"], c)) for i in itens] for c in campos}
    else:
        json_saida = {config.get("saida") or "dados": [copia(i["json"]) for i in itens]}
    return Resultado(saidas=[[{"json": json_saida}]])


def _ou_nulo(valor):
    return None if valor is AUSENTE else copia(valor)


def _numeros(itens, campo):
    valores = []
    for item in itens:
        bruto = obter(item["json"], campo)
        if bruto is AUSENTE or bruto is None or bruto == "":
            continue
        numero = para_numero(bruto)
        if isinstance(numero, float) and math.isnan(numero):
            continue
        valores.append(numero)
    return valores


def _operar(operacao, itens, campo):
    if operacao == "contar":
        return len(itens)
    if operacao == "contar_unicos":
        return len({_impressao(obter(i["json"], campo)) for i in itens})
    if operacao == "concatenar":
        partes = [obter(i["json"], campo) for i in itens]
        return ", ".join(
            formatar_numero(p) if isinstance(p, int | float) and not isinstance(p, bool) else str(p)
            for p in partes
            if p is not AUSENTE and p is not None
        )
    numeros = _numeros(itens, campo)
    if operacao == "somar":
        return normalizar_numero(sum(numeros)) if numeros else 0
    if not numeros:
        return None
    if operacao == "media":
        return normalizar_numero(sum(numeros) / len(numeros))
    return normalizar_numero(min(numeros) if operacao == "min" else max(numeros))


@tipo("resumir")
def resumir(ctx, no, entradas):
    config = no["config"]
    agrupar = config.get("agrupar_por", [])
    grupos = {}
    for item in entradas[0]:
        chave = "|".join(_impressao(obter(item["json"], c)) for c in agrupar)
        grupos.setdefault(chave, []).append(item)
    saida = []
    for itens in grupos.values():
        linha = {}
        for campo in agrupar:
            valor = obter(itens[0]["json"], campo)
            definir(linha, campo, None if valor is AUSENTE else valor)
        for operacao in config.get("operacoes", []):
            campo = operacao.get("campo", "")
            linha[f"{operacao.get('op')}_{campo}"] = _operar(operacao.get("op"), itens, campo)
        saida.append({"json": linha})
    conferir_limite([saida])
    return Resultado(saidas=[saida])


# ---------------------------------------------------------------- Data e hora
_UNIDADE_SOMA = {
    "dias": "days", "horas": "hours", "minutos": "minutes", "semanas": "weeks", "meses": "months",
}  # fmt: skip
_UNIDADE_INICIO = {"dia": "day", "semana": "week", "mes": "month", "hora": "hour"}
_SEGUNDOS = {"dias": 86400, "horas": 3600, "minutos": 60, "semanas": 604800}


def _meses_entre(a, b):
    meses = (b.year - a.year) * 12 + (b.month - a.month)
    resto_a = (a.day, a.hour, a.minute, a.second, a.microsecond)
    resto_b = (b.day, b.hour, b.minute, b.second, b.microsecond)
    if meses > 0 and resto_b < resto_a:
        meses -= 1
    elif meses < 0 and resto_b > resto_a:
        meses += 1
    return meses


def _data_do_campo(json_item, campo):
    valor = obter(json_item, campo)
    if valor is AUSENTE or valor is None:
        raise FalhaNo("expressao", f"O campo '{campo}' não existe ou está vazio.")
    return para_data(valor)


@tipo("data_hora")
def data_hora(ctx, no, entradas):
    config = no["config"]
    operacao = config.get("operacao")
    campo, saida = config.get("campo", ""), config.get("saida") or config.get("campo", "")

    def uma(item, indice, escopo):
        novo = copia(item["json"])
        if operacao == "agora":
            valor = Data(ctx.agora.astimezone(_fuso())).iso()
        else:
            data = _data_do_campo(item["json"], campo)
            unidade = config.get("unidade", "dias")
            if operacao == "formatar":
                valor = Data(data).formatar(config.get("formato", ""))
            elif operacao in ("somar", "subtrair"):
                quantidade = config.get("quantidade", 0)
                if unidade not in _UNIDADE_SOMA:
                    raise FalhaNo("expressao", "Unidade de tempo inválida.")
                sinal = 1 if operacao == "somar" else -1
                valor = Data(somar(data, {_UNIDADE_SOMA[unidade]: quantidade}, sinal)).iso()
            elif operacao == "inicio_de":
                if unidade not in _UNIDADE_INICIO:
                    raise FalhaNo("expressao", "Unidade de tempo inválida.")
                valor = Data(data).inicio_de(_UNIDADE_INICIO[unidade]).iso()
            elif operacao == "diferenca":
                outra = _data_do_campo(item["json"], config.get("campo2", ""))
                if unidade == "meses":
                    valor = _meses_entre(data, outra)
                elif unidade in _SEGUNDOS:
                    valor = math.floor((outra - data).total_seconds() / _SEGUNDOS[unidade])
                else:
                    raise FalhaNo("expressao", "Unidade de tempo inválida.")
            else:
                raise FalhaNo("expressao", "Operação de data inválida.")
        definir(novo, saida, valor)
        return [{"json": novo}]

    return por_item(ctx, no, entradas[0], uma)


def _fuso():
    from ..expressoes.datas import FUSO

    return FUSO


__all__ = ["ErroExpressao", "resolver_texto"]
