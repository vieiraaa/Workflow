"""Demonstração local: Postgres local, dados fictícios. NUNCA carrega o .env nem lê DATABASE_URL."""

import os

import dj_database_url

from config.travas import verificar_banco_teste

from .base import *  # noqa: F403
from .base import INSTALLED_APPS as _APPS

DEBUG = False  # páginas de erro do produto (403/404); estáticos via runserver --insecure
SECRET_KEY = "demo-local-nao-e-segredo"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# apps.nucleo antes do staticfiles: seu runserver serve /static/ com no-cache (T-037).
INSTALLED_APPS = ["apps.nucleo", *(a for a in _APPS if a != "apps.nucleo")]

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

# Só DEMO_DATABASE_URL (outro banco local, se quiser); nunca DATABASE_URL. A trava recusa Supabase.
DATABASES = {
    "default": dj_database_url.parse(
        verificar_banco_teste(
            os.environ.get("DEMO_DATABASE_URL", "postgres://localhost:5432/construtor_demo")
        )
    )
}
