"""Jurídico (M8): painel em 3 colunas, auto-atualização e envio de PDFs, em Chromium e WebKit, light/dark, 1440/390."""

import pytest
from django.urls import reverse

from apps.juridico.models import Carteira, Envio, ItemEnvio, Processo

pytestmark = [
    pytest.mark.modulo("m8"),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture(params=["chromium", "webkit"])
def pagina(request, live_server, cliente_adm):
    from playwright.sync_api import sync_playwright

    sessao = cliente_adm.cookies["sessionid"].value
    with sync_playwright() as pw:
        navegador = getattr(pw, request.param).launch()
        contexto = navegador.new_context(viewport={"width": 1440, "height": 900})
        contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
        p = contexto.new_page()
        yield p
        contexto.close()
        navegador.close()


@pytest.fixture
def processos(usuario_adm):
    carteira = Carteira.objects.get_or_create(nome="Ativos", defaults={"empresa": "ATIVOS S.A."})[0]
    for i in (1, 2):
        Processo.objects.create(
            numero=f"000865{i}-91.2025.8.16.0024", numero_digitos=f"000865{i}9120258160024", numero_valido=True, status=Processo.CONFERIR,
            adverso_nome=f"Parte {i}", carteira=carteira, comarca="Curitiba", criado_por=usuario_adm, criado_via=Processo.PDF, pendencias=[],
        )
    return Processo.objects.order_by("pk")


def _sem_rolagem_horizontal(pagina):
    return pagina.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_painel_desktop_tres_colunas_e_selecao(pagina, live_server, processos, tema):
    pagina.goto(live_server.url + reverse("juridico:painel"))
    pagina.evaluate(f"document.documentElement.dataset.theme = '{tema}'")
    caixas = [pagina.locator(s).bounding_box() for s in (".painel__clientes", ".painel__processos", ".painel__detalhe")]
    assert caixas[0]["x"] < caixas[1]["x"] < caixas[2]["x"]
    assert abs(caixas[0]["y"] - caixas[2]["y"]) < 4
    assert _sem_rolagem_horizontal(pagina)
    segundo = processos[1]
    pagina.click(f'[data-processo="{segundo.pk}"] .proc__link')
    pagina.wait_for_url(f"**?p={segundo.pk}*")
    assert segundo.numero in pagina.locator(".painel__detalhe .detalhe__numero").inner_text()
    pagina.click("a.resumo:has-text(\"Com pendências\")")
    pagina.wait_for_url("**status=COM_PENDENCIAS*")


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_painel_390_uma_coluna_sem_overflow(pagina, live_server, processos, tema):
    pagina.set_viewport_size({"width": 390, "height": 844})
    pagina.goto(live_server.url + reverse("juridico:painel"))
    pagina.evaluate(f"document.documentElement.dataset.theme = '{tema}'")
    assert _sem_rolagem_horizontal(pagina)
    assert not pagina.locator(".painel__detalhe").is_visible()
    assert pagina.locator(".carteiras").is_visible()
    pagina.click(f'[data-processo="{processos[0].pk}"] .proc__link')
    pagina.wait_for_url(f"**/juridico/processos/{processos[0].pk}/")
    assert pagina.locator("[data-form-processo]").count() == 1 and _sem_rolagem_horizontal(pagina)


def test_enviar_pdfs_contagem_e_validacao_no_cliente(pagina, live_server):
    pagina.goto(live_server.url + reverse("juridico:enviar_pdfs"))
    enviar = pagina.locator("[data-form-pdfs] button[type=submit]")
    assert enviar.is_disabled()
    pagina.set_input_files("#arquivos", [{"name": "a.pdf", "mimeType": "application/pdf", "buffer": PDF},
                                         {"name": "b.pdf", "mimeType": "application/pdf", "buffer": PDF + b"x"}])
    assert "2 arquivos escolhidos" in pagina.locator("[data-dropzone-contagem]").inner_text()
    assert pagina.locator("[data-dropzone-lista] li").count() == 2 and enviar.is_enabled()
    pagina.set_input_files("#arquivos", [{"name": f"p{i}.pdf", "mimeType": "application/pdf", "buffer": PDF + bytes([i])} for i in range(11)])
    assert "no máximo 10" in pagina.locator("[data-dropzone-erro]").inner_text() and enviar.is_disabled()
    pagina.set_input_files("#arquivos", [{"name": "x.txt", "mimeType": "text/plain", "buffer": b"oi"}])
    assert "x.txt: não é um PDF." in pagina.locator("[data-dropzone-erro]").inner_text() and enviar.is_disabled()
    pagina.set_input_files("#arquivos", [{"name": "grande.pdf", "mimeType": "application/pdf", "buffer": PDF + b"0" * (31 * 1024 * 1024)}])
    assert "maior que 30 MB" in pagina.locator("[data-dropzone-erro]").inner_text() and enviar.is_disabled()
    pagina.click('[aria-label="Remover grande.pdf"]')
    assert "Nenhum arquivo escolhido." in pagina.locator("[data-dropzone-contagem]").inner_text()


def test_enviar_pdfs_390_sem_overflow(pagina, live_server):
    pagina.set_viewport_size({"width": 390, "height": 844})
    pagina.goto(live_server.url + reverse("juridico:enviar_pdfs"))
    assert _sem_rolagem_horizontal(pagina) and pagina.locator("[data-dropzone]").is_visible()


@pytest.fixture
def envio_na_fila(usuario_adm):
    e = Envio.objects.create(origem=Envio.PDF, enviado_por=usuario_adm)
    return e, ItemEnvio.objects.create(envio=e, nome_arquivo="a.pdf", status=ItemEnvio.NA_FILA)


def test_envio_atualiza_sozinho_e_para(pagina, live_server, envio_na_fila):
    envio, item = envio_na_fila
    pagina.goto(live_server.url + reverse("juridico:envio", kwargs={"pk": envio.pk}))
    assert pagina.locator("[data-envio-andamento]").is_visible()
    ItemEnvio.objects.filter(pk=item.pk).update(status=ItemEnvio.ERRO, motivo="A IA não respondeu")
    pagina.wait_for_selector(f'[data-item="{item.pk}"][data-item-status="erro"]', timeout=20000)
    assert "A IA não respondeu" in pagina.locator("[data-item-motivo]").inner_text()
    assert not pagina.locator("[data-envio-andamento]").is_visible()


def test_painel_atualiza_contagens_e_para_quando_acaba(pagina, live_server, processos, envio_na_fila):
    _, item = envio_na_fila
    pagina.goto(live_server.url + reverse("juridico:painel"))
    assert pagina.locator("[data-painel-aviso]").is_visible()
    assert pagina.locator('[data-resumo="na_fila"]').inner_text() == "1"
    ItemEnvio.objects.filter(pk=item.pk).update(status=ItemEnvio.CONCLUIDO)
    pagina.wait_for_function("document.querySelector('[data-painel-aviso-texto]').textContent.indexOf('concluído') >= 0", timeout=20000)
    assert pagina.locator('[data-resumo="na_fila"]').inner_text() == "0"
    assert pagina.locator("[data-painel-recarregar]").is_visible()
