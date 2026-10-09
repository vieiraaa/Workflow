"""Expressões `{{ ... }}` do motor (MV2-10/11/12 L8, PLH-04). Interpretador próprio, sem eval.

Subconjunto de JavaScript (tokenizador + parser + avaliador em Python puro), lista branca fechada
de funções/métodos, 2.000 caracteres por expressão, 10.000 passos, resultado ≤ 1 MB.

API pública: `Escopo`, `ErroExpressao`, `resolver_texto`, `resolver_valor`, `avaliar`,
`como_texto`, `previa`.
"""

import json
from functools import lru_cache

from .avaliador import MAX_RESULTADO, UNDEF, avaliar_ast, para_json, para_texto, tipo_de
from .erros import CATEGORIA, ErroExpressao
from .parser import parsear

__all__ = [
    "CATEGORIA",
    "ErroExpressao",
    "Escopo",
    "avaliar",
    "como_texto",
    "previa",
    "resolver_texto",
    "resolver_valor",
]

MAX_EXPRESSAO = 2000


class Escopo:
    """Dados que a expressão enxerga.

    `item` é o item atual ({"json": ...}); `entrada` a lista de itens de entrada do nó;
    `resultados` mapeia título do nó → itens da saída 0 do último run; `contexto` aceita
    agora (datetime), execucao_id, fluxo_nome, usuario_email, parametros, pagina, resposta.
    """

    def __init__(self, item=None, indice=0, entrada=(), resultados=None, **contexto):
        self.item = item
        self.indice = indice
        self.entrada = list(entrada)
        self.resultados = resultados if resultados is not None else {}
        self.contexto = contexto


@lru_cache(maxsize=1024)
def _ast(fonte):
    return parsear(fonte)


def _avaliar_js(fonte, escopo):
    if len(fonte) > MAX_EXPRESSAO:
        raise ErroExpressao("A expressão passa de 2.000 caracteres.", fonte)
    return avaliar_ast(_ast(fonte), escopo, fonte)


def _conferir_tamanho(valor, fonte):
    if isinstance(valor, str):
        grande = len(valor) > MAX_RESULTADO
    elif isinstance(valor, list | dict):
        grande = len(json.dumps(valor, ensure_ascii=False, default=str)) > MAX_RESULTADO
    else:
        grande = False
    if grande:
        raise ErroExpressao("O valor resolvido passa de 1 MB.", fonte)


def avaliar(fonte, escopo):
    """Valor tipado (pronto para JSON; undefined → None) da expressão `fonte` (sem as chaves)."""
    bruto = _avaliar_js(fonte, escopo)
    valor = None if bruto is UNDEF else para_json(bruto)
    _conferir_tamanho(valor, fonte)
    return valor


previa = avaliar


def como_texto(valor):
    """Texto de um valor tipado: null/undefined = ''; lista/objeto = JSON compacto."""
    if valor is None or valor is UNDEF:
        return ""
    if isinstance(valor, str):
        return valor
    if tipo_de(valor) in ("array", "object"):
        return json.dumps(para_json(valor), ensure_ascii=False, separators=(",", ":"))
    return para_texto(valor)


def _blocos(texto):
    """Itera (inicio, fim, expressao) de cada `{{ expr }}`; respeita strings e chaves internas."""
    posicao = 0
    while True:
        inicio = texto.find("{{", posicao)
        if inicio == -1:
            return
        i, nivel, fim = inicio + 2, 0, None
        while i < len(texto):
            c = texto[i]
            if c in "'\"`":
                i += 1
                while i < len(texto) and texto[i] != c:
                    i += 2 if texto[i] == "\\" else 1
            elif c == "{":
                nivel += 1
            elif c == "}":
                if nivel == 0 and texto.startswith("}}", i):
                    fim = i
                    break
                nivel = max(nivel - 1, 0)
            i += 1
        if fim is None:
            raise ErroExpressao("Expressão sem fechamento '}}'.", texto[inicio:])
        yield inicio, fim + 2, texto[inicio + 2 : fim]
        posicao = fim + 2


def _template(texto):
    return texto[1:] if texto.startswith("=") else texto


def resolver_texto(texto, escopo, formatar=None):
    """Texto com cada `{{ expr }}` substituído (valor virado texto e, depois, `formatar`)."""
    if not isinstance(texto, str):
        return texto
    texto = _template(texto)
    saida, posicao = [], 0
    for inicio, fim, fonte in _blocos(texto):
        valor = como_texto(avaliar(fonte, escopo))
        saida.append(texto[posicao:inicio])
        saida.append(formatar(valor) if formatar else valor)
        posicao = fim
    saida.append(texto[posicao:])
    resultado = "".join(saida)
    if len(resultado) > MAX_RESULTADO:
        raise ErroExpressao("O valor resolvido passa de 1 MB.")
    return resultado


def resolver_valor(texto, escopo):
    """Como `resolver_texto`; o campo que é exatamente UM `{{ expr }}` devolve o valor tipado."""
    if not isinstance(texto, str):
        return texto
    corpo = _template(texto).strip()
    blocos = list(_blocos(corpo))
    if len(blocos) == 1 and blocos[0][0] == 0 and blocos[0][1] == len(corpo):
        return avaliar(blocos[0][2], escopo)
    return resolver_texto(texto, escopo)


def tem_expressao(texto):
    return isinstance(texto, str) and (texto.startswith("=") or "{{" in texto)
