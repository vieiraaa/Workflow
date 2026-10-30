"""Servidor central desta máquina: Postgres próprio na porta 8081 (scripts/servidor.py).

Mesmo comportamento da demo (HTTP na rede local, login pelo AD), mas com banco persistente e
compartilhado. NUNCA carrega o .env nem lê DATABASE_URL. A URL do banco e a SECRET_KEY ficam em
~/.construtor-workflows/ (criadas pelo script; nunca no repositório).
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from config.travas import verificar_banco_teste

from .demo import *  # noqa: F403

PASTA_LOCAL = Path.home() / ".construtor-workflows"


def _ler(variavel, arquivo):
    valor = os.environ.get(variavel)
    if valor:
        return valor
    caminho = PASTA_LOCAL / arquivo
    if not caminho.exists():
        raise ImproperlyConfigured(
            f"Servidor central sem {variavel}: rode `python scripts/servidor.py` (cria o banco)."
        )
    return caminho.read_text(encoding="utf-8").strip()


SECRET_KEY = _ler("SECRET_KEY", "servidor_secret_key")
# SERVIDOR_IP (scripts/servidor.py --ip): também atende pelo IP da máquina na rede local.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", *filter(None, [os.environ.get("SERVIDOR_IP")])]

DATABASES = {
    "default": dj_database_url.parse(
        verificar_banco_teste(_ler("SERVIDOR_DATABASE_URL", "servidor_banco_url")),
        conn_max_age=60,
        conn_health_checks=True,
    )
}
