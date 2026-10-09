"""Expressões `{{ ... }}` do motor (MV2-10/11/12 L8). Interpretador próprio, sem eval.

API pública (estável): `Escopo`, `ErroExpressao`, `resolver_texto`, `resolver_valor`, `avaliar`.
"""

import json
import re

CATEGORIA = "expressao"
_BLOCO = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_PASSO = re.compile(r"""\.([A-Za-z_]\w*)|\[(\d+)\]|\[\s*(?:"([^"]*)"|'([^']*)')\s*\]""")
_RAIZ_NO = re.compile(r"""\$\(\s*(?:"([^"]*)"|'([^']*)')\s*\)""")
MAX_RESOLVIDO = 1_000_000


class ErroExpressao(Exception):
    """Erro de expressão (categoria `expressao`); `mensagem` é própria, sem texto de exceção."""

    categoria = CATEGORIA

    def __init__(self, mensagem):
        super().__init__(mensagem)
        self.mensagem = mensagem


class Escopo:
    """Dados que a expressão enxerga. `item` é o item atual ({"json": ...}); `resultados` mapeia
    título do nó → lista de itens da saída 0 do último run."""

    def __init__(self, item=None, indice=0, entrada=(), resultados=None, **contexto):
        self.item = item
        self.indice = indice
        self.entrada = list(entrada)
        self.resultados = resultados if resultados is not None else {}
        self.contexto = contexto


def _passos(texto, posicao):
    achados = []
    while posicao < len(texto):
        achado = _PASSO.match(texto, posicao)
        if achado is None:
            raise ErroExpressao(f"Expressão não suportada: {texto.strip()[:60]}")
        nome, indice, dq, sq = achado.groups()
        achados.append(
            nome
            if nome is not None
            else int(indice)
            if indice is not None
            else (dq if dq is not None else sq)
        )
        posicao = achado.end()
    return achados


def _descer(valor, passos, texto):
    for passo in passos:
        if valor is None:
            raise ErroExpressao(
                f"Não é possível ler '{passo}' de um valor vazio em: {texto.strip()[:60]}"
            )
        if isinstance(passo, int):
            valor = valor[passo] if isinstance(valor, list) and passo < len(valor) else None
        else:
            valor = valor.get(passo) if isinstance(valor, dict) else None
    return valor


def avaliar(expr, escopo):
    """Valor TIPADO da expressão `expr` (sem as chaves)."""
    texto = expr.strip()
    if len(texto) > 2000:
        raise ErroExpressao("A expressão passa de 2.000 caracteres.")
    if texto.startswith("$json"):
        base = escopo.item["json"] if escopo.item else None
        return _descer(base, _passos(texto, 5), texto)
    achado = _RAIZ_NO.match(texto)
    if achado:
        titulo = achado.group(1) if achado.group(1) is not None else achado.group(2)
        if titulo not in escopo.resultados:
            raise ErroExpressao(f"O nó '{titulo}' não existe ou ainda não executou.")
        itens = escopo.resultados[titulo]
        resto = texto[achado.end() :]
        for metodo, escolher in (
            (".first()", lambda i: i[0] if i else None),
            (".last()", lambda i: i[-1] if i else None),
        ):
            if resto.startswith(metodo):
                item = escolher(itens)
                resto = resto[len(metodo) :]
                if not resto:
                    return item
                if resto.startswith(".json"):
                    return _descer(item["json"] if item else None, _passos(resto, 5), texto)
        raise ErroExpressao(f"Expressão não suportada: {texto[:60]}")
    raise ErroExpressao(f"Expressão não suportada: {texto[:60]}")


def como_texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, bool):
        return "true" if valor else "false"
    try:
        return json.dumps(valor, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError:
        raise ErroExpressao("O valor não pode ser escrito como JSON.") from None


def resolver_texto(texto, escopo, formatar=None):
    """Texto com cada `{{ expr }}` substituído (valor virado texto, depois `formatar`)."""
    if not isinstance(texto, str):
        return texto
    if texto.startswith("="):
        texto = texto[1:]
    saida, posicao = [], 0
    for achado in _BLOCO.finditer(texto):
        valor = como_texto(avaliar(achado.group(1), escopo))
        saida.append(texto[posicao : achado.start()])
        saida.append(formatar(valor) if formatar else valor)
        posicao = achado.end()
    saida.append(texto[posicao:])
    resultado = "".join(saida)
    if len(resultado) > MAX_RESOLVIDO:
        raise ErroExpressao("O valor resolvido passa de 1 MB.")
    return resultado


def resolver_valor(texto, escopo):
    """Como `resolver_texto`; campo que é exatamente UM `{{ expr }}` devolve o valor tipado."""
    if not isinstance(texto, str):
        return texto
    corpo = texto[1:] if texto.startswith("=") else texto
    unico = _BLOCO.fullmatch(corpo.strip())
    if unico and corpo.strip().count("{{") == 1:
        return avaliar(unico.group(1), escopo)
    return resolver_texto(texto, escopo)
