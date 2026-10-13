"""Auxiliares dos nós: execução por item com tratamento de erro (MV2-05, MV2-12 L6)."""

from apps.fluxos import catalogo

from ..erros import FalhaNo
from ..expressoes import ErroExpressao
from . import LIMITE_ITENS, Resultado


def como_falha(erro):
    if isinstance(erro, FalhaNo):
        return erro
    if isinstance(erro, ErroExpressao):
        return FalhaNo(erro.categoria, erro.mensagem)
    raise erro


def conferir_limite(saidas):
    if sum(len(s) for s in saidas if s) > LIMITE_ITENS:
        raise FalhaNo("limite_itens", "O nó passou de 10.000 itens na saída.")


def por_item(ctx, no, itens, funcao):
    """Roda `funcao(item, indice, escopo)` (devolve lista de itens da saída 0) em cada item.

    Falha por item: `parar` (padrão) levanta; `continuar` segue com o item + json.erro na saída 0;
    `saida_de_erro` manda o item com json.erro para a alça de erro (última saída).
    """
    alvo = itens[:1] if no.get("executar_uma_vez") else itens
    modo = no.get("em_erro", "parar")
    normais = catalogo.n_saidas_normais(no)
    saidas = [[] for _ in range(catalogo.n_saidas(no))]
    resultado = Resultado(saidas=saidas)
    for indice, item in enumerate(alvo):
        try:
            saidas[0].extend(funcao(item, indice, ctx.escopo(item, indice, itens)))
        except (FalhaNo, ErroExpressao) as erro:
            falha = como_falha(erro)
            if modo == "parar":
                raise falha from None
            resultado.erro = resultado.erro or falha
            ctx.diagnostico(falha)
            marcado = {"json": {**item["json"], "erro": falha.como_dict()}}
            saidas[0 if modo == "continuar" else normais].append(marcado)
    conferir_limite(saidas)
    return resultado


def rotear(ctx, no, itens, decidir):
    """Roda `decidir(item, indice, escopo)` por item; devolve a saída (int) ou None (descarta).

    Falha por item como em `por_item`: `continuar` manda o item (com json.erro) para a saída 0;
    `saida_de_erro` para a alça de erro (última saída).
    """
    modo = no.get("em_erro", "parar")
    normais = catalogo.n_saidas_normais(no)
    saidas = [[] for _ in range(catalogo.n_saidas(no))]
    resultado = Resultado(saidas=saidas)
    for indice, item in enumerate(itens):
        try:
            alvo = decidir(item, indice, ctx.escopo(item, indice, itens))
        except (FalhaNo, ErroExpressao) as erro:
            falha = como_falha(erro)
            if modo == "parar":
                raise falha from None
            resultado.erro = resultado.erro or falha
            ctx.diagnostico(falha)
            marcado = {"json": {**item["json"], "erro": falha.como_dict()}}
            saidas[0 if modo == "continuar" else normais].append(marcado)
            continue
        if alvo is not None:
            saidas[alvo].append(item)
    conferir_limite(saidas)
    return resultado
