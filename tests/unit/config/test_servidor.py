import importlib
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

pytestmark = pytest.mark.modulo("m2")


@pytest.fixture
def servidor(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("SECRET_KEY", "chave-ficticia-de-teste")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@aws.pooler.supabase.com:5432/postgres")
    monkeypatch.setenv("SERVIDOR_DATABASE_URL", "postgres://construtor:x@localhost:8081/construtor")
    from config.settings import servidor

    return lambda: importlib.reload(servidor)


def test_servidor_usa_o_banco_central_e_ignora_database_url(servidor):
    banco = servidor().DATABASES["default"]
    assert (banco["HOST"], banco["PORT"], banco["NAME"]) == ("localhost", 8081, "construtor")


def test_servidor_recusa_supabase(servidor, monkeypatch):
    monkeypatch.setenv("SERVIDOR_DATABASE_URL", "postgres://u:p@db.x.supabase.co:5432/postgres")
    with pytest.raises(ImproperlyConfigured):
        servidor()


def test_servidor_sem_url_nem_arquivo_pede_o_script(servidor, monkeypatch):
    monkeypatch.delenv("SERVIDOR_DATABASE_URL")
    with pytest.raises(ImproperlyConfigured, match="scripts/servidor.py"):
        servidor()


def test_servidor_le_url_e_chave_dos_arquivos_locais(servidor, monkeypatch, tmp_path):
    monkeypatch.delenv("SERVIDOR_DATABASE_URL")
    monkeypatch.delenv("SECRET_KEY")
    pasta = tmp_path / ".construtor-workflows"
    pasta.mkdir()
    (pasta / "servidor_banco_url").write_text("postgres://c:s@localhost:8081/construtor\n")
    (pasta / "servidor_secret_key").write_text("chave-do-arquivo\n")
    modulo = servidor()
    assert modulo.SECRET_KEY == "chave-do-arquivo"
    assert modulo.DATABASES["default"]["PORT"] == 8081


def test_servidor_nao_carrega_dotenv_nem_usa_chave_fixa_da_demo():
    fonte = Path("config/settings/servidor.py").read_text(encoding="utf-8")
    assert "dotenv" not in fonte
    assert "SECRET_KEY = _ler(" in fonte
