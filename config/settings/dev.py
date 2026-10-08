"""Desenvolvimento: banco da aplicação via DATABASE_URL (Supabase, session pooler)."""

import os

import dj_database_url
from dotenv import load_dotenv

from .base import *  # noqa: F403
from .base import BASE_DIR
from .base import INSTALLED_APPS as _APPS

load_dotenv(BASE_DIR / ".env")

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# Chave só para dev local, sem valor de segredo; ambientes reais definem SECRET_KEY.
SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-nao-usar-em-producao"

# apps.nucleo antes do staticfiles: seu runserver serve /static/ com no-cache (T-037).
INSTALLED_APPS = ["apps.nucleo", *(a for a in _APPS if a != "apps.nucleo")]

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

_url = os.environ.get("DATABASE_URL")
DATABASES = {
    "default": dj_database_url.parse(
        _url or "postgres://localhost:5432/construtor_dev",
        conn_max_age=60,
        conn_health_checks=True,
        ssl_require=bool(_url),
    )
}
