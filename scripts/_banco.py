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
