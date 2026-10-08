"""Smoke do histórico de execuções (TEL-06): a linha inteira abre o detalhe (EXE-15 a)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.execucoes.models import Execucao
from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = [
    pytest.mark.modulo("m3"),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


@pytest.fixture
def execucao(usuario_coordenador):
    fluxo = Fluxo.objects.create(nome="Linha", dono=usuario_coordenador, grafo=grafo_inicial())
    return Execucao.objects.create(
        fluxo=fluxo,
        fluxo_nome=fluxo.nome,
        grafo_snapshot=fluxo.grafo,
        executado_por=usuario_coordenador,
        status="sucesso",
        finalizada_em=timezone.now(),
    )


@pytest.mark.parametrize("celula", [".tabela__papel", ".tabela__extra", ".tabela__status", ".tabela__principal"])
def test_clicar_em_qualquer_parte_da_linha_abre_o_detalhe(
    pagina_coordenador, live_server, execucao, celula
):
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("execucoes:lista"))
    pagina.locator(f".tabela__linha {celula}").first.click(force=True)
    pagina.wait_for_url(live_server.url + reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}))


def test_clicar_no_no_do_desenho_abre_o_bloco_do_no(
    pagina_coordenador, live_server, usuario_coordenador
):
    from apps.execucoes.models import ExecucaoNo

    grafo = grafo_inicial()
    grafo["nos"] += [
        {"id": "n2", "tipo": "http", "titulo": "Buscar", "posicao": {"x": 340, "y": 120}, "config": {}},
        {"id": "n3", "tipo": "saida", "titulo": "Fim", "posicao": {"x": 600, "y": 120}, "config": {}},
    ]
    grafo["arestas"] = [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n3"}]
    fluxo = Fluxo.objects.create(nome="Desenho", dono=usuario_coordenador, grafo=grafo)
    exe = Execucao.objects.create(
        fluxo=fluxo, fluxo_nome="Desenho", grafo_snapshot=grafo,
        executado_por=usuario_coordenador, status="erro", finalizada_em=timezone.now(),
        erro_resumo="Falhou",
    )
    for ordem, (no_id, tipo, titulo, status) in enumerate(
        [("n1", "gatilho", "Início", "sucesso"), ("n2", "http", "Buscar", "erro"),
         ("n3", "saida", "Fim", "nao_executado")]
    ):
        ExecucaoNo.objects.create(
            execucao=exe, no_id=no_id, no_tipo=tipo, no_titulo=titulo, ordem=ordem,
            status=status, duracao_ms=10,
        )
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("execucoes:detalhe", kwargs={"pk": exe.pk}))
    pagina.wait_for_selector(".fluxo-exec__no")
    assert pagina.locator(".fluxo-exec__no").count() == 3
    assert pagina.locator("[data-no-exec='n1']").evaluate("e => e.open") is False
    pagina.click(".fluxo-exec__no[data-no='n1']")
    assert pagina.locator("[data-no-exec='n1']").evaluate("e => e.open") is True
    assert pagina.locator("[data-no-exec='n3']").evaluate("e => e.open") is False
    # 390 px: o desenho cabe sem rolagem horizontal
    pagina.set_viewport_size({"width": 390, "height": 800})
    pagina.wait_for_timeout(200)
    assert pagina.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    palco = pagina.locator("[data-palco]").bounding_box()
    mundo = pagina.locator(".fluxo-exec__mundo").bounding_box()
    assert mundo["width"] <= palco["width"] + 1


def test_linha_nao_usa_link_esticado(pagina_coordenador, live_server, execucao):
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("execucoes:lista"))
    assert pagina.locator("tr[data-href]").first.get_attribute("data-href") == reverse(
        "execucoes:detalhe", kwargs={"pk": execucao.pk}
    )
    pos = pagina.evaluate(
        "getComputedStyle(document.querySelector('.tabela__link'), '::after').position"
    )
    assert pos != "absolute"
    # clique direto numa célula (sem force): nada cobre a linha
    pagina.locator(".tabela__papel").first.click()
    pagina.wait_for_url(live_server.url + reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}))
