import pytest
from django.core.exceptions import ImproperlyConfigured

from config.travas import verificar_banco_teste

pytestmark = pytest.mark.modulo("m0")


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:senha-x@aws-0-sa-east-1.pooler.supabase.com:5432/postgres",
        "postgres://u:p@db.abc.supabase.co:5432/postgres",
        "postgres://u:p@HOST.SUPABASE.COM/postgres",
    ],
)
def test_trava_aborta_para_supabase_sem_vazar_url(url):
    with pytest.raises(ImproperlyConfigured) as erro:
        verificar_banco_teste(url)
    assert "senha-x" not in str(erro.value)
    assert "supabase.com" not in str(erro.value)


def test_trava_aceita_postgres_local():
    url = "postgres://localhost:5432/construtor_teste"
    assert verificar_banco_teste(url) == url


def test_ssrf_liberar_vazio_em_todos_os_ambientes():
    import importlib

    for modulo in ("base", "dev", "teste"):
        assert importlib.import_module(f"config.settings.{modulo}").MOTOR_SSRF_LIBERAR == []
