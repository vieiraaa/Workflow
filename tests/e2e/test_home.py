"""Smoke da Home (TEL-13): trocar o período atualiza números e gráfico; a última execução abre o detalhe."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.execucoes.models import Execucao
from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = [
    pytest.mark.modulo("m4"),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


@pytest.fixture
def execucoes(usuario_coordenador):
    """1 execução agora (entra em todos os períodos) e 3 há 3 dias (fora das 24h)."""
    fluxo = Fluxo.objects.create(nome="Pedidos", dono=usuario_coordenador, grafo=grafo_inicial(), setor=usuario_coordenador.setor)
    agora = timezone.now()
    criadas = []
    for quando, status in [(agora - timedelta(minutes=1), "sucesso")] + [(agora - timedelta(days=3, hours=i), s) for i, s in enumerate(["sucesso", "sucesso", "erro"])]:
        criadas.append(Execucao.objects.create(
            fluxo=fluxo, fluxo_nome=fluxo.nome, grafo_snapshot=fluxo.grafo, executado_por=usuario_coordenador,
            status=status, setor=fluxo.setor, iniciada_em=quando, finalizada_em=quando + timedelta(seconds=2),
        ))
    return criadas


def valor(pagina, chave):
    return pagina.locator(f'[data-indicador="{chave}"]').get_attribute("data-valor")


def test_trocar_periodo_atualiza_numeros_e_grafico(pagina_coordenador, live_server, execucoes):
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("inicio"))
    assert valor(pagina, "execucoes") == "4"
    assert pagina.locator("svg.g-svg[role=img]").count() == 1
    assert pagina.locator("svg.g-svg[role=img] .g-sucesso").count() >= 1
    pagina.locator(".segmentado__opcao", has_text="24 horas").click()
    pagina.wait_for_url("**periodo=24h")
    assert valor(pagina, "execucoes") == "1"
    assert pagina.locator('[aria-current="true"]', has_text="24 horas").count() == 1
    assert pagina.locator("svg.g-svg[role=img] .g-alvo").count() == 24  # 24 horas
    # Ver dados: tabela equivalente
    pagina.locator(".grafico__dados summary").first.click()
    assert pagina.locator(".grafico__dados table").first.is_visible()


def test_clicar_na_ultima_execucao_abre_o_detalhe(pagina_coordenador, live_server, execucoes):
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("inicio"))
    recente = execucoes[0]
    pagina.locator(f'tr[data-execucao="{recente.pk}"] .tabela__papel').click(force=True)
    pagina.wait_for_url(live_server.url + reverse("execucoes:detalhe", kwargs={"pk": recente.pk}))


def test_tooltip_do_grafico_por_teclado(pagina_coordenador, live_server, execucoes):
    pagina = pagina_coordenador
    pagina.goto(live_server.url + reverse("inicio"))
    pagina.locator("svg.g-svg[role=img]").focus()
    tip = pagina.locator(".g-tip")
    assert tip.is_visible() and "Sucesso" in tip.inner_text()
    pagina.keyboard.press("ArrowLeft")
    assert tip.is_visible()
