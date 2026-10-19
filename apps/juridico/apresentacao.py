"""Formatação para as telas e mensagens do cadastro (texto puro: o template escapa)."""

import re
from decimal import Decimal

from django.utils import timezone

from . import cnj


def data(valor):
    return valor.strftime("%d/%m/%Y") if valor else ""


def data_hora(valor):
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else ""


def valor_texto(valor):
    if valor is None:
        return ""
    inteiro, _, centavos = f"{Decimal(valor):,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _mascarar_um(documento):
    digitos = cnj.so_digitos(documento)
    if len(digitos) == 11:
        return f"***.{digitos[3:6]}.{digitos[6:9]}-**"
    if len(digitos) == 14:
        return f"**.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-**".replace("**.", "**.", 1)
    return "•••"


def mascarar_documento(texto):
    """CPF → ***.456.789-**; CNPJ → **.345.678/0001-**; outro tamanho → •••; vários: um a um."""
    partes = [p for p in re.split(r"\s*;\s*", texto or "") if p.strip()]
    return "; ".join(_mascarar_um(p) for p in partes)


def quem(usuario):
    if usuario is None:
        return "um usuário removido"
    return f"{usuario.nome or usuario.email} ({usuario.email})"


def origem_rotulo(origem):
    return {"pdf": "PDF", "cnj": "CNJ", "manual": "manual"}.get(origem, origem)


def nome(usuario):
    return (usuario.nome or usuario.email) if usuario is not None else "um usuário removido"
