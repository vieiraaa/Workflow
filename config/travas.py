"""Travas de segurança de ambiente."""

from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured


def verificar_banco_teste(url):
    """Aborta se o banco de teste apontar para o Supabase (nunca imprime a URL)."""
    if "supabase" in (urlparse(url).hostname or "").lower() or "supabase" in url.lower():
        raise ImproperlyConfigured(
            "Trava de segurança: o banco de teste aponta para o Supabase. "
            "Testes usam só o Postgres local (TEST_DATABASE_URL)."
        )
    return url
