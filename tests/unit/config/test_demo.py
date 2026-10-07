import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

pytestmark = pytest.mark.modulo("m2")


def test_demo_usa_banco_local_e_ignora_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@aws.pooler.supabase.com:5432/postgres")
    monkeypatch.delenv("DEMO_DATABASE_URL", raising=False)
    from config.settings import demo

    demo = importlib.reload(demo)
    banco = demo.DATABASES["default"]
    assert banco["NAME"] == "construtor_demo"
    assert banco["HOST"] == "localhost"
    assert demo.DEBUG is True


def test_demo_recusa_host_supabase(monkeypatch):
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgres://u:p@db.x.supabase.co:5432/postgres")
    from config.settings import demo

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(demo)
    monkeypatch.delenv("DEMO_DATABASE_URL")
    importlib.reload(demo)


def test_demo_nao_carrega_dotenv():
    from pathlib import Path

    fonte = Path("config/settings/demo.py").read_text(encoding="utf-8")
    assert "dotenv" not in fonte and "load_dotenv" not in fonte


def test_ssrf_liberar_vazio_no_demo():
    from config.settings import demo

    assert demo.MOTOR_SSRF_LIBERAR == []
