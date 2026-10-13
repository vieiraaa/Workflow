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


def test_nos_novos_ficam_alinhados_na_mesma_linha(
    pagina_coordenador, live_server, usuario_coordenador
):
    fluxo = Fluxo.objects.create(nome="Linha", dono=usuario_coordenador, grafo=grafo_inicial())
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")
    pagina.click("[data-paleta-tipo=http]")
    pagina.click("[data-paleta-tipo=saida]")
    ys = pagina.evaluate(
        "[...document.querySelectorAll('.drawflow-node')].map(n => Math.round(n.getBoundingClientRect().y))"
    )
    assert len(ys) == 3 and len(set(ys)) == 1


def test_icone_do_no_centralizado_na_caixa(pagina_coordenador, live_server, usuario_coordenador):
    fluxo = Fluxo.objects.create(nome="Icone", dono=usuario_coordenador, grafo=grafo_inicial())
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")
    # O CSS do Drawflow põe position:absolute em todo svg; o ícone do nó precisa seguir o fluxo.
    pos = pagina.evaluate(
        "getComputedStyle(document.querySelector('.drawflow .no__icone svg')).position"
    )
    assert pos == "static"


# ---------- T-067: navegação infinita ----------


def _abrir(pagina, live_server, usuario):
    fluxo = Fluxo.objects.create(nome="Nav", dono=usuario, grafo=grafo_inicial())
    pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina.wait_for_selector(".drawflow-node")
    pagina.wait_for_timeout(100)


def _pos(pagina):
    return pagina.evaluate(
        "({x: window.editorFlux.editor.canvas_x, y: window.editorFlux.editor.canvas_y,"
        " z: window.editorFlux.editor.zoom})"
    )


def _arrastar(pagina, de, para, steps=6):
    pagina.mouse.move(*de)
    pagina.mouse.down()
    pagina.mouse.move(*para, steps=steps)
    pagina.mouse.up()


def _area(pagina):
    return pagina.locator("[data-canvas]").bounding_box()


def test_pan_em_qualquer_ponto_do_fundo_apos_pan_longo_e_zoom_out(
    pagina_coordenador, live_server, usuario_coordenador
):
    pagina = pagina_coordenador
    _abrir(pagina, live_server, usuario_coordenador)
    pagina.evaluate(
        "(() => { const e = window.editorFlux.editor; e.zoom = 0.4; e.zoom_last_value = 0.4;"
        " e.canvas_x = 3000; e.canvas_y = 3000; e.zoom_refresh(); })()"
    )
    a = _area(pagina)
    pontos = [
        (a["x"] + 20, a["y"] + 200),
        (a["x"] + a["width"] - 20, a["y"] + 200),
        (a["x"] + 20, a["y"] + a["height"] - 20),
        (a["x"] + a["width"] - 20, a["y"] + a["height"] - 20),
        (a["x"] + a["width"] / 2, a["y"] + a["height"] / 2),
    ]
    for x, y in pontos:
        antes = _pos(pagina)
        _arrastar(pagina, (x, y), (x - 15, y - 15))
        depois = _pos(pagina)
        assert depois["x"] != antes["x"] and depois["y"] != antes["y"], (x, y)


def test_arraste_do_fundo_continua_fora_da_area_e_solta_fora(
    pagina_coordenador, live_server, usuario_coordenador
):
    pagina = pagina_coordenador
    _abrir(pagina, live_server, usuario_coordenador)
    a = _area(pagina)
    antes = _pos(pagina)
    pagina.mouse.move(a["x"] + a["width"] - 40, a["y"] + a["height"] - 60)
    pagina.mouse.down()
    pagina.mouse.move(a["x"] + a["width"] + 100, a["y"] + a["height"] - 60, steps=6)  # inspector
    pagina.mouse.up()
    depois = _pos(pagina)
    assert depois["x"] - antes["x"] > 100  # passou da borda do canvas
    pagina.mouse.move(a["x"] + 200, a["y"] + 300)  # sem canvas "grudado" no mouse
    assert _pos(pagina) == depois


def test_grade_acompanha_pan_e_zoom(pagina_coordenador, live_server, usuario_coordenador):
    pagina = pagina_coordenador
    _abrir(pagina, live_server, usuario_coordenador)
    a = _area(pagina)
    _arrastar(pagina, (a["x"] + 30, a["y"] + 300), (a["x"] + 130, a["y"] + 350))
    p = _pos(pagina)
    grade = pagina.evaluate(
        "(() => { const s = document.querySelector('[data-canvas]').style;"
        " return [s.getPropertyValue('--grade-x'), s.getPropertyValue('--grade-y'),"
        " s.getPropertyValue('--grade-z')]; })()"
    )
    assert grade == [f"{p['x']}px", f"{p['y']}px", str(p["z"])]
    pagina.keyboard.down("Control")
    pagina.mouse.move(a["x"] + 300, a["y"] + 300)
    pagina.mouse.wheel(0, 100)
    pagina.keyboard.up("Control")
    z = pagina.evaluate(
        "document.querySelector('[data-canvas]').style.getPropertyValue('--grade-z')"
    )
    assert z == str(_pos(pagina)["z"])


def test_roda_sem_ctrl_move_e_com_ctrl_da_zoom(
    pagina_coordenador, live_server, usuario_coordenador
):
    pagina = pagina_coordenador
    _abrir(pagina, live_server, usuario_coordenador)
    a = _area(pagina)
    pagina.mouse.move(a["x"] + 300, a["y"] + 300)
    antes = _pos(pagina)
    pagina.mouse.wheel(40, 80)
    depois = _pos(pagina)
    assert depois["x"] == antes["x"] - 40 and depois["y"] == antes["y"] - 80
    assert depois["z"] == antes["z"]
    pagina.keyboard.down("Shift")
    pagina.mouse.wheel(0, 50)
    pagina.keyboard.up("Shift")
    assert _pos(pagina)["x"] == depois["x"] - 50
    pagina.keyboard.down("Control")
    pagina.mouse.wheel(0, 100)
    pagina.keyboard.up("Control")
    assert _pos(pagina)["z"] != antes["z"]


def test_pan_de_20000px_e_ajustar_volta(pagina_coordenador, live_server, usuario_coordenador):
    pagina = pagina_coordenador
    _abrir(pagina, live_server, usuario_coordenador)
    a = _area(pagina)
    pagina.mouse.move(a["x"] + 300, a["y"] + 300)
    antes = _pos(pagina)
    for _ in range(20):
        pagina.mouse.wheel(0, 1000)
    assert _pos(pagina)["y"] == antes["y"] - 20000
    pagina.click("[data-acao=ajustar]")
    assert abs(_pos(pagina)["y"] - antes["y"]) < 200


def test_espaco_e_botao_do_meio_movem_mesmo_sobre_um_no(
    pagina_coordenador, live_server, usuario_coordenador
):
    pagina = pagina_coordenador
    _abrir(pagina, live_server, usuario_coordenador)
    no = pagina.locator(".drawflow-node").first.bounding_box()
    centro = (no["x"] + no["width"] / 2, no["y"] + no["height"] / 2)
    posicao_no = pagina.evaluate("window.editorFlux.extrair().nos[0].posicao")
    antes = _pos(pagina)
    pagina.keyboard.down("Space")
    _arrastar(pagina, centro, (centro[0] + 60, centro[1] + 40))
    pagina.keyboard.up("Space")
    depois = _pos(pagina)
    assert depois["x"] - antes["x"] == 60 and depois["y"] - antes["y"] == 40
    assert pagina.evaluate("window.editorFlux.extrair().nos[0].posicao") == posicao_no
    pagina.mouse.move(*centro)
    pagina.mouse.down(button="middle")
    pagina.mouse.move(centro[0] - 30, centro[1], steps=3)
    pagina.mouse.up(button="middle")
    assert _pos(pagina)["x"] == depois["x"] - 30


def test_legenda_de_navegacao_visivel_em_1440_e_390(
    navegador, live_server, usuario_coordenador, cliente_coordenador
):
    fluxo = Fluxo.objects.create(nome="Leg", dono=usuario_coordenador, grafo=grafo_inicial())
    sessao = cliente_coordenador.cookies["sessionid"].value
    for largura, altura in ((1440, 900), (390, 844)):
        contexto = navegador.new_context(viewport={"width": largura, "height": altura})
        contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
        pagina = contexto.new_page()
        pagina.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
        pagina.wait_for_selector(".drawflow-node")
        legenda = pagina.locator(".canvas__legenda")
        assert legenda.is_visible(), largura
        caixa = legenda.bounding_box()
        assert caixa["x"] >= 0 and caixa["x"] + caixa["width"] <= largura, largura
        assert caixa["y"] + caixa["height"] <= altura
        contexto.close()
