"""Entradas de uma Função (FUN-05) e validação dos parâmetros recebidos (FUN-07)."""

import json
import math
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")
MAX_ENTRADAS = 10
MAX_TEXTO = 500
MAX_OPCOES = 50
MAX_OPCAO = 80
TIPOS = ("texto", "numero", "data", "booleano", "lista")
RELATIVOS = ("hoje", "ontem")
_NOME = re.compile(r"^[a-z][a-z0-9_]{0,29}$")


class EntradaInvalida(ValueError):
    """Definição de entradas inválida; `str(erro)` é o motivo curto (FUN-05)."""


class ValorInvalido(ValueError):
    """Valor de parâmetro fora do padrão do tipo (sem o rótulo; a view monta a mensagem)."""


def hoje():
    return datetime.now(FUSO).date()


def _data(valor):
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        raise ValorInvalido
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError:
        raise ValorInvalido from None


def _numero(valor):
    if isinstance(valor, bool):
        raise ValorInvalido
    if isinstance(valor, str):
        texto = valor.strip().replace(",", ".")
        if not re.fullmatch(r"[+-]?\d+(\.\d+)?", texto):
            raise ValorInvalido
        valor = float(texto)
    if not isinstance(valor, int | float) or (
        isinstance(valor, float) and not math.isfinite(valor)
    ):
        raise ValorInvalido
    if abs(valor) > 1e15:
        raise ValorInvalido
    return int(valor) if float(valor).is_integer() else float(valor)


def _booleano(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.lower() in ("true", "on", "1", "sim"):
        return True
    if isinstance(valor, str) and valor.lower() in ("false", "off", "0", "nao", "não", ""):
        return False
    raise ValorInvalido


def converter(entrada, bruto):
    """Valor tipado de `bruto` (padrão ou texto do POST). `ValorInvalido` se inválido."""
    tipo = entrada["tipo"]
    if tipo == "texto":
        if not isinstance(bruto, str):
            raise ValorInvalido
        if len(bruto) > MAX_TEXTO:
            raise ValorInvalido
        return bruto
    if tipo == "numero":
        return _numero(bruto)
    if tipo == "data":
        return _data(bruto)
    if tipo == "booleano":
        return _booleano(bruto)
    if bruto not in entrada.get("opcoes", []):
        raise ValorInvalido
    return bruto


def validar_definicao(lista):
    """Lista de entradas normalizada. Levanta `EntradaInvalida` com o motivo curto."""
    if not isinstance(lista, list):
        raise EntradaInvalida("precisa ser uma lista")
    if len(lista) > MAX_ENTRADAS:
        raise EntradaInvalida(f"no máximo {MAX_ENTRADAS} entradas")
    vistos, saida = set(), []
    for bruta in lista:
        if not isinstance(bruta, dict):
            raise EntradaInvalida("entrada mal formada")
        nome = bruta.get("nome")
        if not isinstance(nome, str) or not _NOME.match(nome):
            raise EntradaInvalida("nome inválido (use minúsculas, números e _)")
        if nome in vistos:
            raise EntradaInvalida(f"nome repetido '{nome}'")
        vistos.add(nome)
        tipo = bruta.get("tipo")
        if tipo not in TIPOS:
            raise EntradaInvalida(f"tipo inválido em '{nome}'")
        rotulo = bruta.get("rotulo")
        rotulo = rotulo.strip() if isinstance(rotulo, str) and rotulo.strip() else nome
        if len(rotulo) > 80:
            raise EntradaInvalida(f"rótulo longo demais em '{nome}'")
        opcoes = bruta.get("opcoes") or []
        if tipo == "lista":
            if (
                not isinstance(opcoes, list)
                or not 1 <= len(opcoes) <= MAX_OPCOES
                or not all(isinstance(o, str) and 0 < len(o) <= MAX_OPCAO for o in opcoes)
            ):
                raise EntradaInvalida(f"opções inválidas em '{nome}'")
        else:
            opcoes = []
        entrada = {
            "nome": nome,
            "rotulo": rotulo,
            "tipo": tipo,
            "obrigatoria": bool(bruta.get("obrigatoria", False)),
            "padrao": None,
            "opcoes": opcoes,
        }
        padrao = bruta.get("padrao")
        if padrao is not None and padrao != "":
            try:
                if tipo == "data" and padrao in RELATIVOS:
                    entrada["padrao"] = padrao
                else:
                    entrada["padrao"] = converter(entrada, padrao)
            except ValorInvalido:
                raise EntradaInvalida(f"padrão inválido em '{nome}'") from None
        saida.append(entrada)
    return saida


def ler_json(texto):
    """Entradas a partir do JSON do POST (campo escondido)."""
    try:
        return validar_definicao(json.loads(texto or "[]"))
    except (ValueError, RecursionError) as erro:
        if isinstance(erro, EntradaInvalida):
            raise
        raise EntradaInvalida("JSON inválido") from None


def padrao_resolvido(entrada):
    """Padrão pronto para o formulário (FUN-05): 'hoje'/'ontem' viram data (São Paulo)."""
    padrao = entrada.get("padrao")
    if padrao == "hoje":
        return hoje().isoformat()
    if padrao == "ontem":
        return (hoje() - timedelta(days=1)).isoformat()
    return padrao


def tem_caractere_proibido(texto):
    """NUL ou surrogate isolado: 400 (MV2-25 c)."""
    if not isinstance(texto, str):
        return False
    try:
        texto.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return "\x00" in texto


def validar_valores(entradas, dados):
    """(valores, erros) de `dados` (QueryDict); chaves desconhecidas são ignoradas (FUN-07).

    `erros` mapeia nome → mensagem. Booleano ausente = False.
    """
    valores, erros = {}, {}
    for entrada in entradas:
        nome, rotulo, tipo = entrada["nome"], entrada["rotulo"], entrada["tipo"]
        bruto = dados.get(nome)
        if tipo == "booleano":
            try:
                valores[nome] = _booleano(bruto) if bruto is not None else False
            except ValorInvalido:
                erros[nome] = f"{rotulo}: valor inválido."
            continue
        bruto = (bruto or "").strip() if isinstance(bruto, str) or bruto is None else bruto
        if bruto == "" and padrao_resolvido(entrada) is not None:
            bruto = str(padrao_resolvido(entrada))
        if bruto == "":
            if entrada["obrigatoria"]:
                erros[nome] = f"Preencha {rotulo}."
            else:
                valores[nome] = None
            continue
        if tipo == "texto" and len(bruto) > MAX_TEXTO:
            erros[nome] = f"{rotulo}: máximo de {MAX_TEXTO} caracteres."
            continue
        try:
            valores[nome] = converter(entrada, bruto)
        except ValorInvalido:
            erros[nome] = {
                "numero": f"{rotulo}: informe um número.",
                "data": f"{rotulo}: data inválida.",
                "lista": f"{rotulo}: opção inválida.",
            }.get(tipo, f"{rotulo}: valor inválido.")
    return valores, erros
