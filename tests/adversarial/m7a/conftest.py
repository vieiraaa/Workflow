"""Fixtures do ADVERSARIAL M7a (Funções). Só pela spec: docs/spec/funcoes.yaml, seguranca.yaml. HTTP só em servidor local.

Reaproveita as fixtures do aceite m7a (mundo7, criar_funcao, exec_funcao…) e do m5 (servidor local, liberado, h…).
"""
import pytest

from tests.acceptance.m7a.conftest import *  # noqa: F401,F403


@pytest.fixture(params=["chromium", "webkit"])
def abrir_pagina(request, live_server):
    """abrir_pagina(usuario) → página Playwright logada (1280x800) contra o live_server; coleta diálogos e erros de JS."""
    from django.test import Client
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        navegador = getattr(pw, request.param).launch()
        paginas = []

        def _abrir(usuario):
            c = Client()
            c.force_login(usuario)
            ctx = navegador.new_context(viewport={"width": 1280, "height": 800})
            ctx.add_cookies([{"name": "sessionid", "value": c.cookies["sessionid"].value, "url": live_server.url}])
            p = ctx.new_page()
            p.live_url = live_server.url
            p.dialogos, p.erros_js = [], []
            p.on("dialog", lambda d: (p.dialogos.append(d.message), d.dismiss()))
            p.on("pageerror", lambda e: p.erros_js.append(str(e)))
            paginas.append(p)
            return p

        yield _abrir
        navegador.close()
