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

DATABASES = {
    "default": dj_database_url.parse(
        verificar_banco_teste(
            os.environ.get("TEST_DATABASE_URL", "postgres://localhost:5432/construtor_teste")
        )
    )
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
