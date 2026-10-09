"""Gatilho manual, Saída e Sem operação."""

from django.utils import timezone

from . import Resultado, tipo


@tipo("gatilho")
def gatilho(ctx, no, entradas):
    item = {
        "json": {
            "disparado_em": timezone.now().isoformat(),
            "executado_por": ctx.usuario.email,
        }
    }
    return Resultado(saidas=[[item]])


@tipo("saida")
def saida(ctx, no, entradas):
    return Resultado(saidas=[list(entradas[0])])  # o resultado fica registrado na própria Saída


@tipo("sem_operacao")
def sem_operacao(ctx, no, entradas):
    return Resultado(saidas=[list(entradas[0])])
