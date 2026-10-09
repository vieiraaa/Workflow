"""Utilidades dos nós de dados: caminho a.b em itens, conversão de datas."""

import copy
import re

from ..erros import FalhaNo
from ..expressoes.datas import FUSO, interpretar_iso

AUSENTE = object()


def obter(objeto, caminho):
    """Valor em `objeto` para `a.b.c` (só dicts; lista por índice numérico). `AUSENTE` se não há."""
    atual = objeto
    for parte in [p for p in str(caminho).split(".") if p]:
        if isinstance(atual, dict) and parte in atual:
            atual = atual[parte]
        elif isinstance(atual, list) and parte.isdigit() and int(parte) < len(atual):
            atual = atual[int(parte)]
        else:
            return AUSENTE
    return atual


def definir(objeto, caminho, valor):
    """Grava `valor` em `a.b.c` criando objetos intermediários."""
    partes = [p for p in str(caminho).split(".") if p]
    if not partes:
        raise FalhaNo("expressao", "O nome do campo está vazio.")
    for parte in partes[:-1]:
        proximo = objeto.get(parte)
        if not isinstance(proximo, dict):
            proximo = objeto[parte] = {}
        objeto = proximo
    objeto[partes[-1]] = valor


def remover(objeto, caminho):
    partes = [p for p in str(caminho).split(".") if p]
    for parte in partes[:-1]:
        objeto = objeto.get(parte) if isinstance(objeto, dict) else None
        if not isinstance(objeto, dict):
            return
    if partes and isinstance(objeto, dict):
        objeto.pop(partes[-1], None)


def ultimo_segmento(caminho):
    partes = [p for p in str(caminho).split(".") if p]
    return partes[-1] if partes else str(caminho)


def copia(json_item):
    return copy.deepcopy(json_item)


def para_data(valor):
    """datetime aware (São Paulo) de ISO 8601 (sem offset = São Paulo) ou epoch em ms."""
    from datetime import datetime

    if isinstance(valor, bool):
        raise FalhaNo("expressao", "Valor de data inválido.")
    if isinstance(valor, int | float):
        return datetime.fromtimestamp(valor / 1000, FUSO)
    if isinstance(valor, str):
        achado = interpretar_iso(valor) if re.search(r"\d", valor) else None
        if achado is not None:
            return achado
    raise FalhaNo("expressao", "Valor de data inválido.")
