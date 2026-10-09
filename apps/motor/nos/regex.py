"""Regex seguro para condições (NOV-02, MV2-15 B8): até 200 caracteres, sem backtracking
catastrófico evidente (repetição ilimitada dentro de repetição ou de alternância) e, quando o
processo permite (thread principal), interrompido em 50 ms."""

import re
import signal
import threading
from contextlib import contextmanager
from functools import lru_cache

from ..erros import FalhaNo

try:  # Python 3.11+
    from re import _constants as _c
    from re import _parser as _p
except ImportError:  # pragma: no cover
    import sre_constants as _c
    import sre_parse as _p

MAX_PADRAO = 200
MAX_TEXTO = 100_000
TEMPO_MAX = 0.05
_REPETICOES = (_c.MAX_REPEAT, _c.MIN_REPEAT)


def _perigoso(sub, dentro=False):
    for operacao, arg in sub:
        if operacao in _REPETICOES or operacao == getattr(_c, "POSSESSIVE_REPEAT", None):
            _, maximo, filho = arg
            ilimitado = maximo > 20
            if dentro and ilimitado:
                return True
            if _perigoso(filho, dentro or ilimitado):
                return True
        elif operacao == _c.SUBPATTERN:
            if _perigoso(arg[-1], dentro):
                return True
        elif operacao == _c.BRANCH:
            if dentro:
                return True
            if any(_perigoso(alt, dentro) for alt in arg[1]):
                return True
        elif operacao in (_c.ASSERT, _c.ASSERT_NOT, getattr(_c, "ATOMIC_GROUP", None)):
            if _perigoso(arg[-1], dentro):
                return True
    return False


@lru_cache(maxsize=256)
def compilar(padrao):
    if len(padrao) > MAX_PADRAO:
        raise FalhaNo("expressao", "A regex passa de 200 caracteres.")
    try:
        analisado = _p.parse(padrao)
        compilado = re.compile(padrao)
    except re.error, RecursionError, OverflowError:
        raise FalhaNo("expressao", "A regex é inválida.") from None
    if _perigoso(analisado):
        raise FalhaNo("expressao", "A regex foi recusada por risco de lentidão (50 ms).")
    return compilado


@contextmanager
def _limite_de_tempo():
    if (
        not hasattr(signal, "setitimer")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def estourou(signum, frame):
        raise TimeoutError

    anterior = signal.signal(signal.SIGALRM, estourou)
    signal.setitimer(signal.ITIMER_REAL, TEMPO_MAX)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, anterior)


def procurar(padrao, texto):
    """True se `padrao` casa em algum ponto de `texto`; erro de nó `expressao` se estourar."""
    compilado = compilar(padrao)
    if len(texto) > MAX_TEXTO:
        raise FalhaNo("expressao", "O texto da regex passa de 100.000 caracteres.")
    try:
        with _limite_de_tempo():
            return compilado.search(texto) is not None
    except TimeoutError:
        raise FalhaNo("expressao", "A regex estourou o limite de 50 ms.") from None
