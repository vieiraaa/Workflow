"""Fixtures do e2e: navegador Playwright (Chromium headless) contra o live_server do Django."""

import os

import pytest

# O Playwright síncrono roda um event loop; o ORM do teste é só preparo de dados.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture
def navegador():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def pagina_coordenador(navegador, live_server, cliente_coordenador):
    """Página já autenticada como Coordenador (cookie de sessão do cliente de teste)."""
    sessao = cliente_coordenador.cookies["sessionid"].value
    contexto = navegador.new_context(viewport={"width": 1440, "height": 900})
    contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
    pagina = contexto.new_page()
    yield pagina
    contexto.close()
