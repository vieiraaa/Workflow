"""Render das telas de execuções (M3): histórico (TEL-06) e detalhe (TEL-07)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.modulo("m3")


def nomes(resposta):
    return [t.name for t in resposta.templates]


def test_historico_usa_template_e_estado_vazio(cliente_base):
    resposta = cliente_base.get(reverse("execucoes:lista"))
    assert resposta.status_code == 200
    assert "execucoes/lista.html" in nomes(resposta)
    assert b"Nenhuma execu" in resposta.content


@pytest.fixture
def execucao(usuario_coordenador):
    from django.utils import timezone

    from apps.execucoes.models import Execucao, ExecucaoNo
    from apps.fluxos.models import Fluxo, grafo_inicial

    fluxo = Fluxo.objects.create(nome="Pedidos", dono=usuario_coordenador, grafo=grafo_inicial())
    agora = timezone.now()
    exe = Execucao.objects.create(
        fluxo=fluxo,
        fluxo_nome=fluxo.nome,
        grafo_snapshot=fluxo.grafo,
        executado_por=usuario_coordenador,
        status="erro",
        finalizada_em=agora,
        erro_resumo="Falhou",
    )
    ExecucaoNo.objects.create(
        execucao=exe,
        no_id="n2",
        no_tipo="http",
        no_titulo="Buscar",
        ordem=2,
        status="erro",
        entrada={"metodo": "GET", "url": "https://api.exemplo.test/x"},
        saida={
            "status": 500,
            "headers": {"x-teste": "<b>oi</b>"},
            "corpo": "<script>alert(1)</script>",
            "truncado": True,
        },
        erro_categoria="http_5xx",
        erro_mensagem="Erro 500",
        duracao_ms=120,
    )
    return exe


def test_detalhe_usa_template_e_escapa_corpo(cliente_coordenador, execucao):
    resposta = cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}))
    assert "execucoes/detalhe.html" in nomes(resposta)
    conteudo = resposta.content.decode()
    assert "<script>alert(1)</script>" not in conteudo
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in conteudo
    assert "&lt;b&gt;oi&lt;/b&gt;" in conteudo
    assert "Resposta truncada" in conteudo and 'data-categoria="http_5xx"' in conteudo


def test_historico_lista_execucao(cliente_coordenador, execucao):
    resposta = cliente_coordenador.get(reverse("execucoes:lista"))
    assert reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}).encode() in resposta.content


def test_detalhe_tem_resumo_card_do_fluxo_e_blocos_com_id(cliente_coordenador, execucao):
    resposta = cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}))
    conteudo = resposta.content.decode()
    assert "data-resumo-execucao" in conteudo
    assert 'id="fluxo-executado"' in conteudo and 'id="grafo-execucao"' in conteudo
    assert 'data-no-exec="n2"' in conteudo
    assert "Abrir fluxo no editor" in conteudo


def test_titulo_do_no_no_desenho_e_escapado(cliente_coordenador, execucao):
    execucao.grafo_snapshot["nos"][0]["titulo"] = "</script><b>x</b>"
    execucao.save()
    resposta = cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}))
    conteudo = resposta.content.decode()
    assert "</script><b>x</b>" not in conteudo


def test_linha_do_historico_e_clicavel(cliente_coordenador, execucao):
    resposta = cliente_coordenador.get(reverse("execucoes:lista"))
    assert b"tabela__linha--clicavel" in resposta.content
