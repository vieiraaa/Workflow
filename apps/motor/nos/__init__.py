"""Registro dos executores de nó (NOV-01). Cada tipo registra `executar(ctx, no, entradas)`.

`entradas` é uma lista (uma por alça de entrada) de listas de itens `{"json": {...}}`.
Devolve `Resultado`: `saidas` (uma lista por alça de saída; `None` = não entregar nada àquela
alça nesta rodada) mais diagnósticos já seguros para gravar.
"""

from dataclasses import dataclass, field

LIMITE_ITENS = 10_000
REGISTRO = {}


@dataclass
class Resultado:
    saidas: list
    erro: object = None  # primeira FalhaNo tolerada (em_erro continuar/saida_de_erro)
    logs: list = field(default_factory=list)
    requisicoes: list = field(default_factory=list)


def tipo(nome):
    def registrar(funcao):
        REGISTRO[nome] = funcao
        return funcao

    return registrar


def carregar():
    """Importa os módulos que registram tipos (evita ciclo de importação)."""
    from . import basicos, codigo, condicoes, dados, fluxo, http  # noqa: F401
