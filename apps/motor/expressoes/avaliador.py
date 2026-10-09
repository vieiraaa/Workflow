"""Avaliador da AST (MV2-10/11/12): semântica JavaScript sobre valores Python, lista branca fechada.

Valores: `UNDEF` (undefined), None (null), bool, int/float, str, list, dict, `Data`, e os objetos
internos `_Namespace` (Math, JSON, Object), `_Funcao` (Number, String, ...) e `_Itens` (o que
`$input` e `$('Nó')` devolvem). Nada é executado fora dos ramos explícitos abaixo.
"""

import json
import math
import re
from urllib.parse import quote

from .datas import PROPRIEDADES, Data, agora
from .erros import ErroExpressao

MAX_PASSOS = 10_000
MAX_RESULTADO = 1_000_000
PROIBIDOS = ("__proto__", "constructor", "prototype")
_INT_SEGURO = 2**53


class _Indefinido:
    __slots__ = ()

    def __repr__(self):
        return "undefined"

    def __bool__(self):
        return False


UNDEF = _Indefinido()


class _Namespace:
    def __init__(self, nome, metodos):
        self.nome, self.metodos = nome, metodos


class _Funcao:
    def __init__(self, nome, chamada):
        self.nome, self.chamada = nome, chamada


class _Itens:
    """`$input` / `$('Título')`: first/last/all/item sobre uma lista de itens."""

    def __init__(self, itens, item):
        self.itens, self.item = itens, item


def tipo_de(v):
    if v is UNDEF:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int | float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, Data):
        return "date"
    return "function"


def normalizar_numero(n):
    if isinstance(n, float) and math.isfinite(n) and n == int(n) and abs(n) < _INT_SEGURO:
        return int(n)
    return n


def formatar_numero(n):
    n = normalizar_numero(n)
    if isinstance(n, float):
        if math.isnan(n):
            return "NaN"
        if math.isinf(n):
            return "Infinity" if n > 0 else "-Infinity"
        return repr(n)
    return str(n)


def para_numero(v):
    t = tipo_de(v)
    if t == "number":
        return v
    if t == "boolean":
        return int(v)
    if t == "null":
        return 0
    if t == "string":
        texto = v.strip()
        if texto == "":
            return 0
        if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", texto):
            return normalizar_numero(float(texto)) if re.search(r"[.eE]", texto) else int(texto)
        if texto in ("Infinity", "+Infinity"):
            return math.inf
        if texto == "-Infinity":
            return -math.inf
        return math.nan
    return math.nan


def para_texto(v):
    """ToString do JavaScript."""
    t = tipo_de(v)
    if t == "string":
        return v
    if t == "undefined":
        return "undefined"
    if t == "null":
        return "null"
    if t == "boolean":
        return "true" if v else "false"
    if t == "number":
        return formatar_numero(v)
    if t == "array":
        return ",".join("" if x is None or x is UNDEF else para_texto(x) for x in v)
    if t == "date":
        return v.iso()
    return "[object Object]"


def verdadeiro(v):
    t = tipo_de(v)
    if t in ("undefined", "null"):
        return False
    if t == "boolean":
        return v
    if t == "number":
        return not (v == 0 or (isinstance(v, float) and math.isnan(v)))
    if t == "string":
        return v != ""
    return True


def igual_estrito(a, b):
    ta, tb = tipo_de(a), tipo_de(b)
    if ta != tb:
        return False
    if ta in ("array", "object", "date"):
        return a is b
    if ta == "number":
        return a == b and not (isinstance(a, float) and math.isnan(a))
    return a == b


def igual_frouxo(a, b):
    ta, tb = tipo_de(a), tipo_de(b)
    if ta == tb:
        return igual_estrito(a, b)
    if ta in ("undefined", "null") and tb in ("undefined", "null"):
        return True
    if ta in ("undefined", "null") or tb in ("undefined", "null"):
        return False
    if ta == "boolean":
        return igual_frouxo(int(a), b)
    if tb == "boolean":
        return igual_frouxo(a, int(b))
    if {ta, tb} == {"number", "string"}:
        return igual_estrito(para_numero(a), para_numero(b))
    if ta in ("array", "object") and tb in ("number", "string"):
        return igual_frouxo(para_texto(a), b)
    if tb in ("array", "object") and ta in ("number", "string"):
        return igual_frouxo(a, para_texto(b))
    return False


def _limite_texto(texto):
    if len(texto) > MAX_RESULTADO:
        raise ErroExpressao("O valor resolvido passa de 1 MB.")
    return texto


def _indice(n, tamanho):
    n = para_numero(n)
    if isinstance(n, float) and math.isnan(n):
        return 0
    n = int(n) if math.isfinite(n) else (tamanho if n > 0 else -tamanho)
    return max(tamanho + n, 0) if n < 0 else min(n, tamanho)


def _fatia(seq, args):
    inicio = _indice(args[0], len(seq)) if args and args[0] is not UNDEF else 0
    fim = _indice(args[1], len(seq)) if len(args) > 1 and args[1] is not UNDEF else len(seq)
    return seq[inicio:fim]


def _para_json(v):
    """Valor serializável em JSON (undefined → ausente; NaN/Infinity → null; Data → ISO)."""
    t = tipo_de(v)
    if t == "number":
        return None if isinstance(v, float) and not math.isfinite(v) else normalizar_numero(v)
    if t == "undefined":
        return None
    if t == "date":
        return v.iso()
    if t == "array":
        return [_para_json(x) for x in v]
    if t == "object":
        return {k: _para_json(x) for k, x in v.items() if x is not UNDEF}
    if t == "function":
        return None
    return v


def para_json(v):
    return _para_json(v)


# --- métodos da lista branca ---------------------------------------------------------------
def _m_texto(receptor, nome, a):
    if nome == "toLowerCase":
        return receptor.lower()
    if nome == "toUpperCase":
        return receptor.upper()
    if nome == "trim":
        return receptor.strip()
    if nome == "split":
        if not a or a[0] is UNDEF:
            return [receptor]
        sep = para_texto(a[0])
        partes = list(receptor) if sep == "" else receptor.split(sep)
        if len(a) > 1 and a[1] is not UNDEF:
            partes = partes[: max(int(para_numero(a[1])), 0)]
        return partes
    if nome == "replace":
        if len(a) < 2 or not isinstance(a[0], str):
            raise ErroExpressao("replace espera dois textos (sem regex).")
        return _limite_texto(receptor.replace(a[0], para_texto(a[1]), 1))
    if nome == "includes":
        return para_texto(a[0] if a else UNDEF) in receptor
    if nome == "startsWith":
        return receptor.startswith(para_texto(a[0] if a else UNDEF))
    if nome == "endsWith":
        return receptor.endswith(para_texto(a[0] if a else UNDEF))
    if nome == "slice":
        return _fatia(receptor, a)
    if nome == "padStart":
        alvo = para_numero(a[0]) if a else 0
        alvo = (
            0 if isinstance(alvo, float) and not math.isfinite(alvo) and alvo != math.inf else alvo
        )
        if alvo > MAX_RESULTADO:
            raise ErroExpressao("O valor resolvido passa de 1 MB.")
        enchimento = " " if len(a) < 2 or a[1] is UNDEF else para_texto(a[1])
        alvo = int(alvo)
        if len(receptor) >= alvo or enchimento == "":
            return receptor
        falta = alvo - len(receptor)
        return (enchimento * (falta // len(enchimento) + 1))[:falta] + receptor
    return None


def _m_lista(receptor, nome, a):
    if nome == "join":
        sep = "," if not a or a[0] is UNDEF else para_texto(a[0])
        return _limite_texto(
            sep.join("" if x is None or x is UNDEF else para_texto(x) for x in receptor)
        )
    if nome == "includes":
        alvo = a[0] if a else UNDEF
        return any(
            igual_estrito(x, alvo) or (x == alvo and tipo_de(x) == tipo_de(alvo) == "number")
            for x in receptor
        )
    if nome == "slice":
        return _fatia(receptor, a)
    if nome == "indexOf":
        alvo = a[0] if a else UNDEF
        return next((i for i, x in enumerate(receptor) if igual_estrito(x, alvo)), -1)
    return None


_NAO = object()


def _numero_arg(a, i=0):
    return para_numero(a[i]) if len(a) > i else math.nan


def _math(nome, a):
    if nome == "round":
        n = _numero_arg(a)
        return n if not math.isfinite(n) else normalizar_numero(math.floor(n + 0.5))
    if nome in ("floor", "ceil"):
        n = _numero_arg(a)
        return n if not math.isfinite(n) else (math.floor(n) if nome == "floor" else math.ceil(n))
    if nome == "abs":
        return normalizar_numero(abs(_numero_arg(a)))
    nums = [para_numero(x) for x in a]
    if any(isinstance(n, float) and math.isnan(n) for n in nums):
        return math.nan
    if nome == "min":
        return min(nums) if nums else math.inf
    if nome == "max":
        return max(nums) if nums else -math.inf
    return _NAO


def _json_parse(a):
    try:
        return json.loads(
            para_texto(a[0] if a else UNDEF),
            parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)),
        )
    except ValueError, RecursionError:
        raise ErroExpressao("JSON.parse recebeu um texto que não é JSON válido.") from None


def _json_stringify(a):
    valor = a[0] if a else UNDEF
    if valor is UNDEF:
        return UNDEF
    return _limite_texto(json.dumps(_para_json(valor), ensure_ascii=False, separators=(",", ":")))


def _parse_int(a):
    texto = para_texto(a[0] if a else UNDEF).strip()
    base = int(para_numero(a[1])) if len(a) > 1 and a[1] is not UNDEF else 10
    achado = re.match(r"[+-]?[0-9a-zA-Z]+", texto) if base != 10 else re.match(r"[+-]?\d+", texto)
    if not achado:
        return math.nan
    try:
        return int(achado.group(0), base)
    except ValueError:
        return math.nan


def _parse_float(a):
    achado = re.match(r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", para_texto(a[0] if a else UNDEF))
    return normalizar_numero(float(achado.group(0))) if achado else math.nan


def _objeto_chaves(a, valores):
    alvo = a[0] if a else UNDEF
    if isinstance(alvo, dict):
        return list(alvo.values() if valores else alvo.keys())
    if isinstance(alvo, list):
        return list(alvo if valores else (str(i) for i in range(len(alvo))))
    raise ErroExpressao("Object.keys/values esperam um objeto ou lista.")


FUNCOES = {
    "Number": lambda a: para_numero(a[0]) if a else 0,
    "String": lambda a: para_texto(a[0]) if a else "",
    "Boolean": lambda a: verdadeiro(a[0]) if a else False,
    "parseInt": _parse_int,
    "parseFloat": _parse_float,
    "isNaN": lambda a: (
        isinstance(para_numero(a[0] if a else UNDEF), float)
        and math.isnan(para_numero(a[0] if a else UNDEF))
    ),
    "encodeURIComponent": lambda a: quote(para_texto(a[0] if a else UNDEF), safe="-_.!~*'()"),
}
NAMESPACES = {
    "Math": ("round", "floor", "ceil", "abs", "min", "max"),
    "JSON": ("stringify", "parse"),
    "Object": ("keys", "values"),
}


class Avaliador:
    def __init__(self, escopo, fonte):
        self.escopo = escopo
        self.fonte = fonte
        self.passos = 0

    # --- erros
    def _erro(self, mensagem):
        return ErroExpressao(mensagem, self.fonte)

    # --- variáveis
    def _variavel(self, nome):
        e = self.escopo
        ctx = e.contexto
        if nome == "$json":
            return e.item["json"] if e.item else {}
        if nome == "$input":
            return _Itens(e.entrada, e.item)
        if nome == "$itemIndex":
            return e.indice
        if nome == "$now":
            return agora(ctx.get("agora"))
        if nome == "$today":
            return agora(ctx.get("agora")).inicio_de("day")
        if nome == "$execution":
            return {"id": ctx.get("execucao_id")}
        if nome == "$workflow":
            return {"name": ctx.get("fluxo_nome", "")}
        if nome == "$usuario":
            return {"email": ctx.get("usuario_email", "")}
        if nome == "$parametros":
            return ctx.get("parametros") or {}
        if nome in ("$pageCount", "$response"):
            chave = "pagina" if nome == "$pageCount" else "resposta"
            return ctx.get(chave, UNDEF)
        if nome == "$":
            return _Funcao("$", self._no_por_titulo)
        if nome in FUNCOES:
            return _Funcao(nome, FUNCOES[nome])
        if nome in NAMESPACES:
            return _Namespace(nome, NAMESPACES[nome])
        if nome == "undefined":
            return UNDEF
        if nome in ("NaN",):
            return math.nan
        if nome == "Infinity":
            return math.inf
        raise self._erro(f"'{nome}' não está disponível nas expressões.")

    def _no_por_titulo(self, a):
        titulo = a[0] if len(a) == 1 and isinstance(a[0], str) else None
        if titulo is None:
            raise self._erro("$() espera o título do nó em texto.")
        resultados = self.escopo.resultados
        if titulo not in resultados:
            raise self._erro(f"O nó '{titulo}' não existe ou ainda não executou.")
        itens = resultados[titulo]
        indice = self.escopo.indice
        item = itens[indice] if indice < len(itens) else (itens[-1] if itens else UNDEF)
        return _Itens(itens, item)

    # --- acesso a propriedade
    def _propriedade(self, obj, chave, opcional):
        if obj is UNDEF or obj is None:
            if opcional:
                return UNDEF
            raise self._erro(f"Não é possível ler '{para_texto(chave)}' de um valor vazio.")
        if isinstance(chave, str) and chave in PROIBIDOS:
            raise self._erro(f"Acesso a '{chave}' não é permitido.")
        t = tipo_de(obj)
        if isinstance(obj, _Itens):
            if chave == "item":
                return obj.item
            return UNDEF  # first/last/all só como chamada
        if t == "object":
            return obj.get(chave if isinstance(chave, str) else para_texto(chave), UNDEF)
        if t == "array":
            if chave == "length":
                return len(obj)
            numero = para_numero(chave) if not isinstance(chave, str) or chave.isdigit() else None
            if numero is not None and isinstance(numero, int) and 0 <= numero < len(obj):
                return obj[numero]
            return UNDEF
        if t == "string":
            if chave == "length":
                return len(obj)
            if (
                isinstance(chave, int | float)
                and not isinstance(chave, bool)
                and 0 <= chave < len(obj)
            ):
                return obj[int(chave)]
            return UNDEF
        if t == "date":
            return obj.propriedade(chave) if chave in PROPRIEDADES else UNDEF
        return UNDEF  # number, boolean, namespaces, funções: nada acessível por propriedade

    # --- chamadas
    def _chamar(self, no, args, opcional):
        destino = no[1]
        if destino[0] == "mem":
            obj_no, chave_no, opc_membro = destino[1], destino[2], destino[3]
            receptor = self._avaliar(obj_no)
            chave = self._avaliar(chave_no)
            if receptor is UNDEF or receptor is None:
                if opc_membro or opcional:
                    return UNDEF
                raise self._erro(f"Não é possível chamar '{para_texto(chave)}' de um valor vazio.")
            if not isinstance(chave, str) or chave in PROIBIDOS:
                raise self._erro("Chamada não permitida.")
            argumentos = [self._avaliar(a) for a in args]
            return self._metodo(receptor, chave, argumentos)
        funcao = self._avaliar(destino)
        if funcao is UNDEF and opcional:
            return UNDEF
        if not isinstance(funcao, _Funcao):
            raise self._erro("Só funções da lista permitida podem ser chamadas.")
        return funcao.chamada([self._avaliar(a) for a in args])

    def _metodo(self, receptor, nome, a):
        if isinstance(receptor, _Namespace):
            if nome not in receptor.metodos:
                raise self._erro(f"{receptor.nome}.{nome} não está na lista permitida.")
            if receptor.nome == "Math":
                return _math(nome, a)
            if receptor.nome == "JSON":
                return _json_stringify(a) if nome == "stringify" else _json_parse(a)
            return _objeto_chaves(a, nome == "values")
        if isinstance(receptor, _Itens):
            if nome == "first":
                return receptor.itens[0] if receptor.itens else UNDEF
            if nome == "last":
                return receptor.itens[-1] if receptor.itens else UNDEF
            if nome == "all":
                return list(receptor.itens)
            raise self._erro(f"Método '{nome}' não permitido.")
        t = tipo_de(receptor)
        if t == "string":
            r = _m_texto(receptor, nome, a)
        elif t == "array":
            r = _m_lista(receptor, nome, a)
        elif t == "date":
            return receptor.chamar(nome, a)
        else:
            r = None
        if r is None and nome not in self._metodos_validos(t):
            raise self._erro(f"Método '{nome}' não permitido.")
        return r

    @staticmethod
    def _metodos_validos(t):
        return {
            "string": ("toLowerCase", "toUpperCase", "trim", "split", "replace", "includes",
                       "startsWith", "endsWith", "slice", "padStart"),
            "array": ("join", "includes", "slice", "indexOf"),
        }.get(t, ())  # fmt: skip

    # --- núcleo
    def _avaliar(self, no):
        self.passos += 1
        if self.passos > MAX_PASSOS:
            raise self._erro("A expressão passou do limite de passos.")
        tipo = no[0]
        if tipo == "lit":
            return no[1]
        if tipo == "var":
            return self._variavel(no[1])
        if tipo == "tpl":
            return _limite_texto(
                "".join(p if isinstance(p, str) else para_texto(self._avaliar(p)) for p in no[1])
            )
        if tipo == "arr":
            return [self._avaliar(x) for x in no[1]]
        if tipo == "obj":
            return {chave: self._avaliar(valor) for chave, valor in no[1] if chave not in PROIBIDOS}
        if tipo == "mem":
            obj = self._avaliar(no[1])
            if no[3] and (obj is UNDEF or obj is None):
                return UNDEF
            return self._propriedade(obj, self._avaliar(no[2]), no[3])
        if tipo == "call":
            return self._chamar(no, no[2], no[3])
        if tipo == "un":
            return self._unario(no[1], self._avaliar(no[2]))
        if tipo == "log":
            return self._logico(no)
        if tipo == "cond":
            return self._avaliar(no[2] if verdadeiro(self._avaliar(no[1])) else no[3])
        return self._cadeia_binaria(no)

    def _cadeia_binaria(self, no):
        """Cadeia à esquerda (a + b + c ...) sem recursão: 1.000 termos não estouram a pilha."""
        operacoes = []
        while no[0] == "bin":
            operacoes.append((no[1], no[3]))
            no = no[2]
        valor = self._avaliar(no)
        for op, direita in reversed(operacoes):
            self.passos += 1
            if self.passos > MAX_PASSOS:
                raise self._erro("A expressão passou do limite de passos.")
            valor = self._binario(op, valor, self._avaliar(direita))
        return valor

    def _logico(self, no):
        op, esquerda = no[1], self._avaliar(no[2])
        if op == "&&":
            return self._avaliar(no[3]) if verdadeiro(esquerda) else esquerda
        if op == "||":
            return esquerda if verdadeiro(esquerda) else self._avaliar(no[3])
        return self._avaliar(no[3]) if esquerda is None or esquerda is UNDEF else esquerda

    def _unario(self, op, v):
        if op == "!":
            return not verdadeiro(v)
        n = para_numero(v)
        return normalizar_numero(-n if op == "-" else n)

    def _binario(self, op, a, b):
        if op == "===":
            return igual_estrito(a, b)
        if op == "!==":
            return not igual_estrito(a, b)
        if op == "==":
            return igual_frouxo(a, b)
        if op == "!=":
            return not igual_frouxo(a, b)
        if op == "+":
            if tipo_de(a) in ("string", "array", "object", "date") or tipo_de(b) in (
                "string", "array", "object", "date"
            ):  # fmt: skip
                return _limite_texto(para_texto(a) + para_texto(b))
            return normalizar_numero(self._somar(para_numero(a), para_numero(b)))
        if op in ("<", "<=", ">", ">="):
            if isinstance(a, str) and isinstance(b, str):
                x, y = a, b
            else:
                x, y = para_numero(a), para_numero(b)
                if any(isinstance(n, float) and math.isnan(n) for n in (x, y)):
                    return False
            return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
        x, y = para_numero(a), para_numero(b)
        if op == "-":
            return normalizar_numero(x - y)
        if op == "*":
            return normalizar_numero(self._multiplicar(x, y))
        if op == "/":
            if y == 0:
                if isinstance(x, float) and math.isnan(x) or x == 0:
                    return math.nan
                return math.inf if x > 0 else -math.inf
            return normalizar_numero(x / y)
        if op == "%":
            if y == 0 or (isinstance(x, float) and not math.isfinite(x)):
                return math.nan
            return normalizar_numero(math.fmod(x, y))
        raise self._erro("Operador não suportado.")

    @staticmethod
    def _somar(x, y):
        return x + y

    @staticmethod
    def _multiplicar(x, y):
        return x * y


def avaliar_ast(ast, escopo, fonte):
    """Valor JS (com UNDEF/Data) da AST; limites de passos e de tamanho aplicados."""
    try:
        valor = Avaliador(escopo, fonte)._avaliar(ast)
    except RecursionError:
        raise ErroExpressao("A expressão tem aninhamento demais.", fonte) from None
    except OverflowError:
        raise ErroExpressao("Número grande demais na expressão.", fonte) from None
    return valor
