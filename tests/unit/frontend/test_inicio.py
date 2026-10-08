"""Render da Home pela view real (TEL-13/16/17): template, estados, escape e atributos do contrato (HOM-09)."""

import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.execucoes.models import Execucao
from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = [pytest.mark.modulo("m4"), pytest.mark.django_db]


def nomes(resposta):
    return [t.name for t in resposta.templates]


@pytest.fixture
def execucao(usuario_coordenador):
    fluxo = Fluxo.objects.create(
        nome="Pedidos <i>x</i>", dono=usuario_coordenador, grafo=grafo_inicial(), setor=usuario_coordenador.setor
    )
    return Execucao.objects.create(
        fluxo=fluxo, fluxo_nome=fluxo.nome, grafo_snapshot=fluxo.grafo, executado_por=usuario_coordenador,
        status="sucesso", setor=fluxo.setor, finalizada_em=timezone.now(),
        iniciada_em=timezone.now() - timedelta(minutes=5),
    )


@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador", "cliente_base"])
def test_home_usa_template_e_shell(request, cliente):
    resposta = request.getfixturevalue(cliente).get(reverse("inicio"))
    assert resposta.status_code == 200
    assert "inicio/inicio.html" in nomes(resposta) and "base.html" in nomes(resposta)
    assert b'data-estado="vazio"' in resposta.content


def test_home_com_dados_tem_cartoes_graficos_e_linha_clicavel(cliente_coordenador, execucao):
    resposta = cliente_coordenador.get(reverse("inicio"))
    html = resposta.content.decode()
    assert 'data-indicador="execucoes"' in html and 'id="home-serie"' in html and 'id="home-erros"' in html
    assert 'id="home-setores"' not in html
    assert f'data-execucao="{execucao.pk}"' in html and f'data-fluxo="{execucao.fluxo_id}"' in html
    assert reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}) in html
    assert "<i>x</i>" not in html and "&lt;i&gt;x&lt;/i&gt;" in html


def test_home_adm_ve_execucoes_por_setor(cliente_adm, execucao):
    html = cliente_adm.get(reverse("inicio")).content.decode()
    assert 'id="home-setores"' in html and "Execuções por setor" in html


def test_home_periodo_marca_opcao_ativa_e_invalido_cai_no_padrao(cliente_coordenador, execucao):
    html = cliente_coordenador.get(reverse("inicio"), {"periodo": "30d"}).content.decode()
    assert re.search(r'href="[^"]*periodo=30d"[^>]*aria-current="true"', html)
    resposta = cliente_coordenador.get(reverse("inicio"), {"periodo": "xx"})
    assert resposta.status_code == 200


def test_home_sem_execucoes_no_periodo_mostra_aviso(cliente_coordenador, execucao):
    Execucao.objects.update(iniciada_em=timezone.now() - timedelta(days=200))
    html = cliente_coordenador.get(reverse("inicio"), {"periodo": "24h"}).content.decode()
    assert 'data-estado="sem_dados_periodo"' in html


def test_menu_tem_inicio_no_topo(cliente_adm):
    html = cliente_adm.get(reverse("inicio")).content.decode()
    assert html.index(f'href="{reverse("inicio")}"') < html.index(f'href="{reverse("fluxos:lista")}"')
