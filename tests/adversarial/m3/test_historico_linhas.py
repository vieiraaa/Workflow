"""T-038 (EXE-15): no histórico /execucoes/ cada linha abre a SUA execução, não a da linha 1.

Caixa-preta, em navegador real (chromium e webkit) a 1440 e 390: clica em três pontos de cada linha
(esquerda, centro, direita) e compara o href do link da linha com a URL aberta. Só dados fictícios,
servidor local.
"""

import os

import pytest
from django.urls import reverse

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

pytestmark = [pytest.mark.modulo("m3"), pytest.mark.django_db(transaction=True, serialized_rollback=True)]

PONTOS = (0.05, 0.5, 0.95)


@pytest.fixture(params=["chromium", "webkit"])
def motor(request):
    return request.param


@pytest.fixture(params=[1440, 390], ids=["1440", "390"])
def largura(request):
    return request.param


@pytest.fixture
def pagina_adm(motor, largura, live_server, cliente_adm):
    from playwright.sync_api import sync_playwright

    sessao = cliente_adm.cookies["sessionid"].value
    with sync_playwright() as pw:
        navegador = getattr(pw, motor).launch()
        contexto = navegador.new_context(viewport={"width": largura, "height": 800})
        contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
        pagina = contexto.new_page()
        pagina.live_url = live_server.url
        yield pagina
        navegador.close()


def test_cada_linha_abre_a_sua_execucao(pagina_adm, executar, cadeia, cfg_http, liberado, cliente_adm, modelos):
    """EXE-15: clicar em qualquer ponto de uma linha do histórico abre a execução daquela linha."""
    for _ in range(4):
        _, execucao, _ = executar(cliente_adm, cadeia(cfg_http(f"{liberado.base}/ok")))
        assert execucao is not None
    assert modelos.Execucao.objects.count() >= 4

    lista = pagina_adm.live_url + reverse("execucoes:lista")
    pagina_adm.goto(lista)
    pagina_adm.wait_for_load_state("networkidle")
    linhas = pagina_adm.locator("tbody tr")
    total = linhas.count()
    assert total >= 4
    hrefs = [linhas.nth(i).locator("a[href]").first.get_attribute("href") for i in range(total)]
    assert len(set(hrefs)) == total, "cada linha deve ter um link próprio"

    erros = []
    for i in range(total):
        for fx in PONTOS:
            pagina_adm.goto(lista)
            pagina_adm.wait_for_load_state("networkidle")
            linha = linhas.nth(i)
            linha.scroll_into_view_if_needed()
            caixa = linha.bounding_box()
            pagina_adm.mouse.click(caixa["x"] + caixa["width"] * fx, caixa["y"] + caixa["height"] / 2)
            try:
                pagina_adm.wait_for_url(lambda u, h=hrefs[i]: u.endswith(h), timeout=3000)
            except Exception:
                erros.append((i, fx, hrefs[i], pagina_adm.url))
    assert not erros, f"cliques que não abriram a execução da própria linha (linha, ponto, esperado, foi): {erros}"
