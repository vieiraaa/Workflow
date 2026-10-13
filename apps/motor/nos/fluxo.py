"""Nós de fluxo (NOV-04, MV2-15 B4/B5, MV2-17): Juntar e Parar com erro."""

from ..erros import FalhaNo
from ..expressoes import resolver_texto
from . import LIMITE_ITENS, Resultado, tipo
from .base import conferir_limite
from .util import AUSENTE, copia, obter


def _mesclar(a, b):
    return {"json": {**copia(a["json"]), **copia(b["json"])}}


def _combinar_por_campo(config, esquerda, direita):
    campo1, campo2 = config.get("campo1", ""), config.get("campo2", "")
    modo = config.get("tipo", "dentro")
    saida, usados = [], set()
    for item in esquerda:
        chave = obter(item["json"], campo1)
        pares = []
        if chave is not AUSENTE and chave is not None:
            pares = [
                (i, d)
                for i, d in enumerate(direita)
                if obter(d["json"], campo2) == chave
                and type(obter(d["json"], campo2)) is type(chave)  # noqa: E721
            ]
        if pares:
            for i, par in pares:
                usados.add(i)
                saida.append(_mesclar(item, par))
        elif modo in ("esquerda", "externa"):
            saida.append(copia_item(item))
    if modo in ("direita", "externa"):
        saida += [copia_item(d) for i, d in enumerate(direita) if i not in usados]
    return saida


def copia_item(item):
    return {"json": copia(item["json"])}


@tipo("juntar")
def juntar(ctx, no, entradas):
    config = no["config"]
    modo = config.get("modo", "anexar")
    esquerda = entradas[0] if entradas else []
    direita = entradas[1] if len(entradas) > 1 else []
    if modo == "anexar":
        saida = [copia_item(i) for entrada in entradas for i in entrada]
    elif modo == "combinar_por_campo":
        saida = _combinar_por_campo(config, esquerda, direita)
    elif modo == "combinar_por_posicao":
        saida = [_mesclar(a, b) for a, b in zip(esquerda, direita, strict=False)]
    else:
        indice = config.get("entrada", 0)
        saida = [copia_item(i) for i in (entradas[indice] if 0 <= indice < len(entradas) else [])]
    if len(saida) > LIMITE_ITENS:
        raise FalhaNo("limite_itens", "O nó passou de 10.000 itens na saída.")
    conferir_limite([saida])
    return Resultado(saidas=[saida])


@tipo("parar_com_erro")
def parar_com_erro(ctx, no, entradas):
    item = entradas[0][0]
    escopo = ctx.escopo(item, 0, entradas[0])
    mensagem = resolver_texto(no["config"].get("mensagem", ""), escopo) or "O fluxo foi parado."
    raise FalhaNo("parado", mensagem[:500])
