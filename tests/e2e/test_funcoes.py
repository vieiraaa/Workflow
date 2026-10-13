"""Smoke das Funções (TEL-23..26) em Chromium e WebKit: editor de entradas, liberação, execução com erro e catálogo."""

import json

import pytest
from django.urls import reverse

from apps.fluxos.models import Fluxo, grafo_inicial
from apps.funcoes.models import Funcao

pytestmark = [
    pytest.mark.modulo("m7a"),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


@pytest.fixture(params=["chromium", "webkit"])
def pagina_adm(request, live_server, cliente_adm):
    from playwright.sync_api import sync_playwright

    sessao = cliente_adm.cookies["sessionid"].value
    with sync_playwright() as pw:
        navegador = getattr(pw, request.param).launch()
        contexto = navegador.new_context(viewport={"width": 1440, "height": 900})
        contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
        yield contexto.new_page()
        contexto.close()
        navegador.close()


@pytest.fixture
def fluxo(usuario_adm):
    return Fluxo.objects.create(nome="Fluxo de apoio", dono=usuario_adm, grafo=grafo_inicial())


def test_editor_de_entradas_salva_e_catalogo_mostra(pagina_adm, live_server, fluxo):
    p = pagina_adm
    p.goto(live_server.url + reverse("funcoes:nova"))
    p.fill("#id_nome", "Consulta diária")
    p.select_option("#id_fluxo", str(fluxo.pk))
    p.click("[data-entrada-adicionar]")
    p.fill("[data-f=nome]", "dia")
    p.fill("[data-f=rotulo]", "Dia")
    p.select_option("[data-f=tipo]", "lista")
    assert p.locator("[data-so-lista]").is_visible()
    p.fill("[data-f=opcoes]", "hoje\nontem")
    p.check("[data-f=obrigatoria]")
    entradas = json.loads(p.input_value("[data-entradas-json]"))
    assert entradas[0]["nome"] == "dia" and entradas[0]["opcoes"] == ["hoje", "ontem"] and entradas[0]["obrigatoria"]
    p.select_option("[data-liberar]", "setores")
    assert p.locator("[data-liberar-para=setores]").is_visible() and not p.locator("[data-liberar-para=papeis]").is_visible()
    p.select_option("[data-liberar]", "todos")
    p.click("form[data-form-funcao] button[type=submit]")
    p.wait_for_load_state()
    assert p.url.endswith(reverse("funcoes:catalogo")), p.url
    assert p.locator(".cartao-funcao", has_text="Consulta diária").count() == 1
    assert p.locator(".cartao-funcao", has_text="Rascunho").count() == 1
    f = Funcao.objects.get(nome="Consulta diária")
    assert f.entradas[0]["tipo"] == "lista"
    # remover a linha zera o JSON
    p.goto(live_server.url + reverse("funcoes:editar", kwargs={"pk": f.pk}))
    assert p.locator("[data-entrada]").count() == 1
    p.click("[data-entrada-remover]")
    assert json.loads(p.input_value("[data-entradas-json]")) == []


def test_executar_com_campo_obrigatorio_vazio_mostra_erro(pagina_adm, live_server, fluxo, usuario_adm):
    f = Funcao.objects.create(
        nome="Com entrada", fluxo=fluxo, versao=1, criada_por=usuario_adm, grafo_publicado=fluxo.grafo,
        entradas=[{"nome": "dia", "rotulo": "Dia", "tipo": "texto", "obrigatoria": True, "padrao": None, "opcoes": []}],
    )
    p = pagina_adm
    p.goto(live_server.url + reverse("funcoes:catalogo"))
    p.click(".cartao-funcao >> text=Executar")
    p.wait_for_url("**" + reverse("funcoes:executar", kwargs={"pk": f.pk}))
    p.click("form[data-form-executar] button[type=submit]")
    p.wait_for_selector(".campo__erro")
    assert "Preencha Dia." in p.inner_text(".campo__erro")
