"""Settings de produção (base.py): flags de segurança ligadas (SEG-11/SEG-12)."""

import logging

import pytest

from config.settings import base


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("DEBUG", False),
        ("SESSION_COOKIE_SECURE", True),
        ("CSRF_COOKIE_SECURE", True),
        ("SESSION_COOKIE_HTTPONLY", True),
        ("SECURE_CONTENT_TYPE_NOSNIFF", True),
        ("X_FRAME_OPTIONS", "DENY"),
        ("MOTOR_SSRF_LIBERAR", []),
    ],
)
def test_flags_de_producao(nome, esperado):
    assert getattr(base, nome) == esperado


def test_hsts_ligado():
    assert base.SECURE_HSTS_SECONDS > 0


def test_loggers_http_em_warning_com_filtro():
    for nome in ("httpx", "httpcore"):
        assert base.LOGGING["loggers"][nome]["level"] == "WARNING"


def test_filtro_mascara_query_sensivel():
    from apps.motor.mascarar import FiltroMascararQuery

    reg = logging.LogRecord(
        "httpx", logging.WARNING, "", 0, 'HTTP "GET %s"', ("http://a/ok?token=XYZ&b=1",), None
    )
    FiltroMascararQuery().filter(reg)
    assert "XYZ" not in reg.getMessage() and "b=1" in reg.getMessage()
