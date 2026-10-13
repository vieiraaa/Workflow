"""Objeto de data estilo Luxon (MV2-11, MV2-12 L10): fuso America/Sao_Paulo, toISO/toFormat/plus…"""

import calendar
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .erros import ErroExpressao

FUSO = ZoneInfo("America/Sao_Paulo")
_TOKENS = re.compile(r"'([^']*)'|yyyy|yy|MM|M|dd|d|HH|H|hh|h|mm|m|ss|s|SSS|a|ZZ|Z")
_UNIDADES = {
    "years": "anos", "year": "anos", "months": "meses", "month": "meses", "weeks": "semanas",
    "week": "semanas", "days": "dias", "day": "dias", "hours": "horas", "hour": "horas",
    "minutes": "minutos", "minute": "minutos", "seconds": "segundos", "second": "segundos",
    "milliseconds": "ms", "millisecond": "ms",
}  # fmt: skip
PROPRIEDADES = ("year", "month", "day", "hour", "minute", "second", "weekday")
METODOS = ("toISO", "toFormat", "plus", "minus", "startOf", "toMillis", "toISODate")


def agora(instante=None):
    return Data((instante or datetime.now(FUSO)).astimezone(FUSO))


def interpretar_iso(texto):
    """ISO 8601; sem offset = São Paulo. None se não for data."""
    try:
        valor = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return valor.astimezone(FUSO) if valor.tzinfo else valor.replace(tzinfo=FUSO)


def _offset(dt, separador):
    total = int(dt.utcoffset().total_seconds() // 60)
    sinal = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sinal}{total // 60:02d}{separador}{total % 60:02d}"


def somar(dt, quantidades, sinal=1):
    for nome, qtd in quantidades.items():
        if nome not in _UNIDADES or isinstance(qtd, bool) or not isinstance(qtd, int | float):
            raise ErroExpressao("Duração inválida em plus/minus.", nome)
        unidade, qtd = _UNIDADES[nome], qtd * sinal
        if unidade in ("anos", "meses"):
            meses = int(qtd) * (12 if unidade == "anos" else 1)
            indice = dt.year * 12 + dt.month - 1 + meses
            ano, mes = divmod(indice, 12)
            dia = min(dt.day, calendar.monthrange(ano, mes + 1)[1])
            dt = dt.replace(year=ano, month=mes + 1, day=dia)
        else:
            chave = {"semanas": "weeks", "dias": "days", "horas": "hours", "minutos": "minutes",
                     "segundos": "seconds", "ms": "milliseconds"}[unidade]  # fmt: skip
            dt = (dt.replace(tzinfo=None) + timedelta(**{chave: qtd})).replace(tzinfo=FUSO)
    return dt


class Data:
    """Data imutável com a API mínima do Luxon DateTime."""

    __slots__ = ("dt",)

    def __init__(self, dt):
        self.dt = dt

    def iso(self):
        return (
            self.dt.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{self.dt.microsecond // 1000:03d}"
            + _offset(self.dt, ":")
        )

    def formatar(self, formato):
        dt = self.dt

        def trocar(achado):
            token = achado.group(0)
            if token.startswith("'"):
                return achado.group(1)
            hora12 = dt.hour % 12 or 12
            return {
                "yyyy": f"{dt.year:04d}", "yy": f"{dt.year % 100:02d}", "MM": f"{dt.month:02d}",
                "M": str(dt.month), "dd": f"{dt.day:02d}", "d": str(dt.day), "HH": f"{dt.hour:02d}",
                "H": str(dt.hour), "hh": f"{hora12:02d}", "h": str(hora12),
                "mm": f"{dt.minute:02d}",
                "m": str(dt.minute), "ss": f"{dt.second:02d}", "s": str(dt.second),
                "SSS": f"{dt.microsecond // 1000:03d}", "a": "AM" if dt.hour < 12 else "PM",
                "ZZ": _offset(dt, ":"), "Z": _offset(dt, ""),
            }[token]  # fmt: skip

        return _TOKENS.sub(trocar, formato)

    def inicio_de(self, unidade):
        dt = self.dt
        if unidade == "year":
            dt = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        elif unidade == "month":
            dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif unidade == "week":
            dt = (dt - timedelta(days=dt.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif unidade == "day":
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif unidade == "hour":
            dt = dt.replace(minute=0, second=0, microsecond=0)
        elif unidade == "minute":
            dt = dt.replace(second=0, microsecond=0)
        else:
            raise ErroExpressao("Unidade inválida em startOf.", unidade)
        return Data(dt)

    def milissegundos(self):
        return int(self.dt.timestamp() * 1000)

    def propriedade(self, nome):
        if nome == "weekday":
            return self.dt.isoweekday()
        return getattr(self.dt, nome)

    def chamar(self, metodo, args):
        if metodo == "toISO":
            return self.iso()
        if metodo == "toISODate":
            return self.dt.strftime("%Y-%m-%d")
        if metodo == "toMillis":
            return self.milissegundos()
        if metodo == "toFormat":
            if len(args) != 1 or not isinstance(args[0], str):
                raise ErroExpressao("toFormat espera um texto de formato.")
            return self.formatar(args[0])
        if metodo == "startOf":
            if len(args) != 1 or not isinstance(args[0], str):
                raise ErroExpressao("startOf espera o nome de uma unidade.")
            return self.inicio_de(args[0])
        if metodo in ("plus", "minus"):
            if len(args) != 1 or not isinstance(args[0], dict):
                raise ErroExpressao(f"{metodo} espera um objeto como {{days: 1}}.")
            return Data(somar(self.dt, args[0], 1 if metodo == "plus" else -1))
        raise ErroExpressao("Método de data não permitido.", metodo)
