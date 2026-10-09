"""Tokenizador e parser (descida recursiva) do subconjunto JavaScript das expressões (MV2-10).

Gera uma AST de tuplas. O que não está na gramática (atribuição, `=>`, `function`, `new`, laços,
`++`, vírgula, regex literal…) é erro de sintaxe: nunca há como executar algo fora da lista.
"""

import re

from .erros import ErroExpressao

MAX_PROFUNDIDADE = 60
_ESPACO = re.compile(r"\s+")
_NUMERO = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_OPERADORES = ("===", "!==", "==", "!=", "<=", ">=", "&&", "||", "??", "?.")
_SIMPLES = "+-*/%<>!?:.,()[]{}"
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _sintaxe(texto=None):
    return ErroExpressao("Sintaxe de expressão inválida ou não suportada.", texto)


def _ler_texto(fonte, i, aspa):
    """Lê a string entre aspas que começa em fonte[i]. Devolve (texto, próximo)."""
    saida, i = [], i + 1
    while i < len(fonte):
        c = fonte[i]
        if c == aspa:
            return "".join(saida), i + 1
        if c == "\\":
            i += 1
            if i >= len(fonte):
                break
            e = fonte[i]
            if e == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", fonte[i + 1 : i + 5] or ""):
                saida.append(chr(int(fonte[i + 1 : i + 5], 16)))
                i += 4
            else:
                saida.append(_ESCAPES.get(e, e))
        else:
            saida.append(c)
        i += 1
    raise _sintaxe(fonte)


def _fim_da_interpolacao(fonte, i):
    """Índice do `}` que fecha uma `${` aberta antes de `i` (respeita strings e chaves)."""
    nivel = 0
    while i < len(fonte):
        c = fonte[i]
        if c in "'\"":
            _, i = _ler_texto(fonte, i, c)
            continue
        if c == "`":
            _, _, i = _ler_template(fonte, i)
            continue
        if c == "{":
            nivel += 1
        elif c == "}":
            if nivel == 0:
                return i
            nivel -= 1
        i += 1
    raise _sintaxe(fonte)


def _ler_template(fonte, i):
    """Template literal a partir de '`'. Devolve (partes, None, próximo); parte = str | expr."""
    partes, atual, i = [], [], i + 1
    while i < len(fonte):
        c = fonte[i]
        if c == "`":
            partes.append("".join(atual))
            return partes, None, i + 1
        if c == "\\" and i + 1 < len(fonte):
            atual.append(_ESCAPES.get(fonte[i + 1], fonte[i + 1]))
            i += 2
            continue
        if c == "$" and fonte[i + 1 : i + 2] == "{":
            fim = _fim_da_interpolacao(fonte, i + 2)
            partes.append("".join(atual))
            atual = []
            partes.append(("expr", fonte[i + 2 : fim]))
            i = fim + 1
            continue
        atual.append(c)
        i += 1
    raise _sintaxe(fonte)


def tokenizar(fonte):
    tokens, i = [], 0
    while i < len(fonte):
        achado = _ESPACO.match(fonte, i)
        if achado:
            i = achado.end()
            continue
        c = fonte[i]
        if c in "'\"":
            valor, i = _ler_texto(fonte, i, c)
            tokens.append(("str", valor))
        elif c == "`":
            partes, _, i = _ler_template(fonte, i)
            tokens.append(("tpl", partes))
        elif c.isdigit() or (c == "." and fonte[i + 1 : i + 2].isdigit()):
            achado = _NUMERO.match(fonte, i)
            texto = achado.group(0)
            numero = float(texto) if re.search(r"[.eE]", texto) else int(texto)
            tokens.append(("num", numero))
            i = achado.end()
        elif _IDENT.match(fonte, i):
            achado = _IDENT.match(fonte, i)
            tokens.append(("id", achado.group(0)))
            i = achado.end()
        else:
            for op in _OPERADORES:
                if fonte.startswith(op, i):
                    if op == "?." and fonte[i + 2 : i + 3].isdigit():
                        continue  # a ?.5 : b
                    tokens.append(("op", op))
                    i += len(op)
                    break
            else:
                if c not in _SIMPLES:
                    raise _sintaxe(fonte)  # inclui '=', ';', '&', '|', '@', '#', '\\' ...
                tokens.append(("op", c))
                i += 1
    return tokens


class _Parser:
    def __init__(self, fonte):
        self.fonte = fonte
        self.tokens = tokenizar(fonte)
        self.pos = 0
        self.nivel = 0

    # --- utilitários
    def _espiar(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def _ehop(self, *ops):
        tipo, valor = self._espiar()
        return tipo == "op" and valor in ops

    def _consumir(self, op):
        if not self._ehop(op):
            raise _sintaxe(self.fonte)
        self.pos += 1

    def _entrar(self):
        self.nivel += 1
        if self.nivel > MAX_PROFUNDIDADE:
            raise ErroExpressao("A expressão tem aninhamento demais.", self.fonte)

    # --- gramática
    def expressao(self):
        self._entrar()
        try:
            return self._condicional()
        finally:
            self.nivel -= 1

    def _condicional(self):
        teste = self._nulo()
        if self._ehop("?"):
            self.pos += 1
            a = self.expressao()
            self._consumir(":")
            b = self.expressao()
            return ("cond", teste, a, b)
        return teste

    def _binario(self, proximo, ops, tipo="bin"):
        esquerda = proximo()
        while self._ehop(*ops):
            op = self.tokens[self.pos][1]
            self.pos += 1
            esquerda = (tipo, op, esquerda, proximo())
        return esquerda

    def _nulo(self):
        return self._binario(self._ou, ("??",), "log")

    def _ou(self):
        return self._binario(self._e, ("||",), "log")

    def _e(self):
        return self._binario(self._igualdade, ("&&",), "log")

    def _igualdade(self):
        return self._binario(self._relacional, ("==", "===", "!=", "!=="))

    def _relacional(self):
        return self._binario(self._soma, ("<", "<=", ">", ">="))

    def _soma(self):
        return self._binario(self._produto, ("+", "-"))

    def _produto(self):
        return self._binario(self._unario, ("*", "/", "%"))

    def _unario(self):
        if self._ehop("!", "-", "+"):
            op = self.tokens[self.pos][1]
            self.pos += 1
            self._entrar()
            try:
                return ("un", op, self._unario())
            finally:
                self.nivel -= 1
        return self._postfixo()

    def _argumentos(self):
        self._consumir("(")
        args = []
        while not self._ehop(")"):
            args.append(self.expressao())
            if self._ehop(","):
                self.pos += 1
            elif not self._ehop(")"):
                raise _sintaxe(self.fonte)
        self._consumir(")")
        return args

    def _postfixo(self):
        no = self._primario()
        while True:
            if self._ehop("."):
                self.pos += 1
                tipo, nome = self._espiar()
                if tipo != "id":
                    raise _sintaxe(self.fonte)
                self.pos += 1
                no = ("mem", no, ("lit", nome), False)
            elif self._ehop("?."):
                self.pos += 1
                if self._ehop("("):
                    no = ("call", no, self._argumentos(), True)
                elif self._ehop("["):
                    self.pos += 1
                    indice = self.expressao()
                    self._consumir("]")
                    no = ("mem", no, indice, True)
                else:
                    tipo, nome = self._espiar()
                    if tipo != "id":
                        raise _sintaxe(self.fonte)
                    self.pos += 1
                    no = ("mem", no, ("lit", nome), True)
            elif self._ehop("["):
                self.pos += 1
                indice = self.expressao()
                self._consumir("]")
                no = ("mem", no, indice, False)
            elif self._ehop("("):
                no = ("call", no, self._argumentos(), False)
            else:
                return no

    def _primario(self):
        tipo, valor = self._espiar()
        if tipo is None:
            raise _sintaxe(self.fonte)
        if tipo == "num":
            self.pos += 1
            return ("lit", valor)
        if tipo == "str":
            self.pos += 1
            return ("lit", valor)
        if tipo == "tpl":
            self.pos += 1
            partes = [p if isinstance(p, str) else _parsear(p[1]) for p in valor]
            return ("tpl", partes)
        if tipo == "id":
            self.pos += 1
            if valor == "true":
                return ("lit", True)
            if valor == "false":
                return ("lit", False)
            if valor == "null":
                return ("lit", None)
            return ("var", valor)
        if self._ehop("("):
            self.pos += 1
            dentro = self.expressao()
            self._consumir(")")
            return dentro
        if self._ehop("["):
            self.pos += 1
            itens = []
            while not self._ehop("]"):
                itens.append(self.expressao())
                if self._ehop(","):
                    self.pos += 1
                elif not self._ehop("]"):
                    raise _sintaxe(self.fonte)
            self._consumir("]")
            return ("arr", itens)
        if self._ehop("{"):
            return self._objeto()
        raise _sintaxe(self.fonte)

    def _objeto(self):
        self._consumir("{")
        pares = []
        while not self._ehop("}"):
            tipo, chave = self._espiar()
            if tipo not in ("id", "str", "num"):
                raise _sintaxe(self.fonte)
            self.pos += 1
            self._consumir(":")
            pares.append((str(chave), self.expressao()))
            if self._ehop(","):
                self.pos += 1
            elif not self._ehop("}"):
                raise _sintaxe(self.fonte)
        self._consumir("}")
        return ("obj", pares)


def _parsear(fonte):
    parser = _Parser(fonte)
    if not parser.tokens:
        raise _sintaxe(fonte)
    ast = parser.expressao()
    if parser.pos != len(parser.tokens):
        raise _sintaxe(fonte)
    return ast


def parsear(fonte):
    """AST da expressão `fonte` (sem as chaves). Levanta ErroExpressao em sintaxe inválida."""
    try:
        return _parsear(fonte)
    except RecursionError:
        raise ErroExpressao("A expressão tem aninhamento demais.", fonte) from None
