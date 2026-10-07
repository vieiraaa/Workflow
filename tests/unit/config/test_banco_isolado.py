import importlib
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.modulo("m2")

RAIZ = Path(__file__).resolve().parents[3]


def _recarregar_teste(monkeypatch, **env):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    for chave, valor in env.items():
        monkeypatch.setenv(chave, valor)
    from config.settings import teste

    return importlib.reload(teste)


def test_nome_do_banco_de_teste_tem_sufixo_do_processo(monkeypatch):
    teste = _recarregar_teste(monkeypatch)
    assert teste.DATABASES["default"]["NAME"] == f"construtor_teste_{os.getpid()}"


def test_sufixo_inclui_o_worker_do_xdist(monkeypatch):
    teste = _recarregar_teste(monkeypatch, PYTEST_XDIST_WORKER="gw3")
    assert teste.DATABASES["default"]["NAME"] == f"construtor_teste_{os.getpid()}_gw3"


def test_url_explicita_vale_como_esta(monkeypatch):
    teste = _recarregar_teste(
        monkeypatch, TEST_DATABASE_URL="postgres://localhost:5432/meu_banco_proprio"
    )
    assert teste.DATABASES["default"]["NAME"] == "meu_banco_proprio"


def test_trava_continua_valendo_na_url_derivada_ou_explicita(monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured):
        _recarregar_teste(monkeypatch, TEST_DATABASE_URL="postgres://x@db.a.supabase.co/postgres")
    _recarregar_teste(monkeypatch)  # restaura o módulo


def test_limpeza_de_orfaos_so_apaga_bancos_do_projeto_de_processos_mortos(monkeypatch):
    monkeypatch.syspath_prepend(str(RAIZ / "scripts"))
    import _banco
    import psycopg

    config = {
        "NAME": "postgres",
        "HOST": "localhost",
        "PORT": None,
        "USER": None,
        "PASSWORD": None,
    }
    morto = "99999998"
    vivo = str(os.getpid())
    nomes = {
        "orfao_teste": f"test_construtor_teste_{morto}",
        "orfao_telas": f"construtor_telas_{morto}",
        "orfao_xdist": f"test_construtor_teste_{morto}_gw1",
        "vivo": f"construtor_telas_{vivo}",
        "alheio": f"outro_projeto_{morto}",
        "sem_pid": "construtor_telas_abc",
    }
    with _banco._conexao_admin(config) as admin:
        for nome in nomes.values():
            admin.execute(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)')
            admin.execute(f'CREATE DATABASE "{nome}"')
    try:
        apagados = set(_banco.limpar_orfaos(config))
        assert {nomes["orfao_teste"], nomes["orfao_telas"], nomes["orfao_xdist"]} <= apagados
        assert not apagados & {nomes["vivo"], nomes["alheio"], nomes["sem_pid"]}
    finally:
        with psycopg.connect(dbname="postgres", host="localhost", autocommit=True) as admin:
            for nome in nomes.values():
                admin.execute(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)')
    assert "scripts" in sys.modules["_banco"].__file__
