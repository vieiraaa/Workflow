"""Testes: Postgres LOCAL. Nunca lê DATABASE_URL nem o .env; aborta se apontar para Supabase."""

import os

import dj_database_url

from config.travas import verificar_banco_teste

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "teste-nao-e-segredo"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0


def _url_do_banco_de_teste():
    """TEST_DATABASE_URL explícita vale como está; senão o nome ganha sufixo único por processo
    (e por worker do xdist), para execuções simultâneas não colidirem no mesmo banco."""
    explicita = os.environ.get("TEST_DATABASE_URL")
    if explicita:
        return explicita
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    sufixo = f"{os.getpid()}{('_' + worker) if worker else ''}"
    return f"postgres://localhost:5432/construtor_teste_{sufixo}"


DATABASES = {"default": dj_database_url.parse(verificar_banco_teste(_url_do_banco_de_teste()))}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
