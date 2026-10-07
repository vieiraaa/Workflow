"""Smoke do editor de canvas (TEL-05): criar 3 nós, conectar, salvar, recarregar, grafo igual."""

import pytest
from django.urls import reverse

from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = [
    pytest.mark.modulo("m2"),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]

URL = "https://api.exemplo.test/pedidos/1"


def _conectar(pagina, de, para):
    saida = pagina.locator(f"#node-{de} .output").bounding_box()
    entrada = pagina.locator(f"#node-{para} .input").bounding_box()
    pagina.mouse.move(saida["x"] + saida["width"] / 2, saida["y"] + saida["height"] / 2)
    pagina.mouse.down()
    pagina.mouse.move(
        entrada["x"] + entrada["width"] / 2, entrada["y"] + entrada["height"] / 2, steps=8
    )
    pagina.mouse.up()


def _grafo(pagina):
    return pagina.evaluate("window.editorFlux.extrair()")


def test_criar_conectar_salvar_recarregar(pagina_coordenador, live_server, usuario_coordenador):
    fluxo = Fluxo.objects.create(nome="Smoke", dono=usuario_coordenador, grafo=grafo_inicial())
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")

    pagina.click("[data-paleta-tipo=http]")
    pagina.click("[data-paleta-tipo=saida]")
    assert pagina.locator(".drawflow-node").count() == 3

    # O último nó criado fica selecionado; seleciona o HTTP e preenche a URL no inspector.
    pagina.locator(".drawflow-node.no-http").click(position={"x": 60, "y": 20})
    pagina.fill("#insp-url", URL)
    pagina.fill("#insp-titulo", "Buscar pedido")

    pagina.click("[data-acao=ajustar]")
    _conectar(pagina, 1, 2)
    _conectar(pagina, 2, 3)
    antes = _grafo(pagina)
    assert len(antes["nos"]) == 3 and len(antes["arestas"]) == 2

    pagina.click("[data-salvar]")
    pagina.wait_for_selector(".toast--success")

    fluxo.refresh_from_db()
    assert fluxo.grafo == antes

    pagina.reload()
    pagina.wait_for_selector(".drawflow-node")
    assert _grafo(pagina) == antes


def test_conflito_409_mostra_aviso(pagina_coordenador, live_server, usuario_coordenador):
    fluxo = Fluxo.objects.create(nome="Conflito", dono=usuario_coordenador, grafo=grafo_inicial())
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")
    Fluxo.objects.filter(pk=fluxo.pk).update(nome="Outro nome")
    fluxo.refresh_from_db()
    Fluxo.objects.get(pk=fluxo.pk).save()  # atualiza atualizado_em
    pagina.click("[data-paleta-tipo=saida]")
    pagina.click("[data-salvar]")
    pagina.wait_for_selector("[data-banner]:not([hidden])")
    assert "alterado por outra pessoa" in pagina.inner_text("[data-banner]")


def test_editor_utilizavel_a_390px(
    navegador, live_server, usuario_coordenador, cliente_coordenador
):
    fluxo = Fluxo.objects.create(nome="Mobile", dono=usuario_coordenador, grafo=grafo_inicial())
    sessao = cliente_coordenador.cookies["sessionid"].value
    contexto = navegador.new_context(viewport={"width": 390, "height": 844})
    contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
    pagina = contexto.new_page()
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")
    assert not pagina.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), (
        "overflow horizontal"
    )
    pagina.click("[data-acao=paleta]")
    pagina.click("[data-paleta-tipo=http]")
    pagina.locator("#insp-url").wait_for(state="visible")
    contexto.close()


def test_executar_a_partir_do_editor_e_ver_detalhe(
    pagina_coordenador, live_server, usuario_coordenador
):
    """Gatilho → saída (sem rede): salva, executa e cai no detalhe com toast de sucesso."""
    fluxo = Fluxo.objects.create(nome="Executável", dono=usuario_coordenador, grafo=grafo_inicial())
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")
    pagina.click("[data-paleta-tipo=saida]")
    pagina.click("[data-acao=ajustar]")
    _conectar(pagina, 1, 2)
    # Executar com alterações não salvas: o editor salva primeiro e só então envia o POST.
    pagina.click("[data-executar] button")
    pagina.wait_for_url("**/execucoes/*/")
    assert pagina.locator(".no-exec").count() == 2
    assert "Execução concluída" in pagina.inner_text("[data-toasts]")
