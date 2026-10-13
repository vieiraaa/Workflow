"""Nó Código (NOV-06, SEG-17, SEG-20): JavaScript no runtime isolado (processo separado, dentro
da camada de rede do SO). Só enxerga os dados que enviamos: itens de entrada, a saída dos nós que
o código cita por `$('Título')`, e o contexto da execução."""

import re

from ..codigo.executor import CodigoErro, executar_codigo
from ..erros import FalhaNo
from . import Resultado, tipo
from .base import conferir_limite

_TITULOS = re.compile(r"""\$\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')\s*\)""")
SEM_TOLERANCIA = ("codigo_limite", "codigo_indisponivel")


def _titulos_citados(codigo):
    return {(a or b).replace("\\'", "'").replace('\\"', '"') for a, b in _TITULOS.findall(codigo)}


def _com_erro(item, falha):
    return {"json": {**item["json"], "erro": falha.como_dict()}}


@tipo("codigo")
def codigo(ctx, no, entradas):
    config = no["config"]
    fonte = config.get("codigo", "")
    modo = config.get("modo", "uma_vez_para_todos")
    itens = entradas[0][:1] if no.get("executar_uma_vez") else entradas[0]
    nos_citados = {t: ctx.resultados[t] for t in _titulos_citados(fonte) if t in ctx.resultados}
    contexto = {
        "agora": ctx.agora.isoformat(),
        "execucao_id": ctx.execucao.pk,
        "fluxo_nome": ctx.fluxo_nome,
        "parametros": getattr(ctx, "parametros", {}),
    }
    modo_erro = no.get("em_erro", "parar")
    saidas = [[], []] if modo_erro == "saida_de_erro" else [[]]
    resultado = Resultado(saidas=saidas)

    def tratar(item, falha):
        if modo_erro == "parar":
            raise falha
        resultado.erro = resultado.erro or falha
        ctx.diagnostico(falha)
        saidas[0 if modo_erro == "continuar" else 1].append(_com_erro(item, falha))

    try:
        resposta = executar_codigo(fonte, itens, modo, nos_citados, contexto)
    except CodigoErro as erro:
        falha = FalhaNo(erro.categoria, erro.mensagem)
        if erro.categoria in SEM_TOLERANCIA:
            raise falha from None
        for item in itens:
            tratar(item, falha)
        return resultado
    resultado.logs = list(resposta.get("logs", []))[:200]
    if modo == "uma_vez_por_item":
        for item, saida in zip(itens, resposta["por_item"], strict=False):
            if "erro" in saida:
                tratar(item, FalhaNo("codigo", saida["erro"]))
            else:
                saidas[0].extend(saida["itens"])
    else:
        saidas[0].extend(resposta["itens"])
    conferir_limite(saidas)
    return resultado
