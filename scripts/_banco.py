"""Criação e remoção de bancos Postgres locais (usado por demo.py e telas.py)."""

import psycopg


def _conexao_admin(config):
    return psycopg.connect(
        dbname="postgres",
        host=config["HOST"] or None,
        port=config["PORT"] or None,
        user=config["USER"] or None,
        password=config["PASSWORD"] or None,
        autocommit=True,
    )


def existe(config):
    with _conexao_admin(config) as admin:
        achou = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config["NAME"],))
        return achou.fetchone() is not None


def criar_se_faltar(config):
    """Cria o banco se não existir. Devolve True se criou."""
    if existe(config):
        return False
    with _conexao_admin(config) as admin:
        admin.execute(f'CREATE DATABASE "{config["NAME"]}"')
    return True


def apagar(config):
    with _conexao_admin(config) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{config["NAME"]}" WITH (FORCE)')


def _pid_vivo(pid):
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def limpar_orfaos(config, prefixos=("test_construtor_teste_", "construtor_telas_")):
    """Apaga bancos temporários do projeto cujo processo (pid no sufixo) já morreu.

    Só mexe em bancos com um dos prefixos do projeto e sufixo numérico; nunca em outros bancos
    e nunca nos de execuções ainda vivas. Devolve os nomes apagados.
    """
    apagados = []
    with _conexao_admin(config) as admin:
        nomes = [linha[0] for linha in admin.execute("SELECT datname FROM pg_database")]
        for nome in nomes:
            for prefixo in prefixos:
                resto = nome[len(prefixo) :] if nome.startswith(prefixo) else ""
                pid = resto.split("_")[0]
                if pid.isdigit() and not _pid_vivo(int(pid)):
                    admin.execute(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)')
                    apagados.append(nome)
    return apagados
