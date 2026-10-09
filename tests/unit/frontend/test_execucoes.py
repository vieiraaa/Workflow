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


@pytest.fixture
def execucao_v2(usuario_coordenador):
    """Execução v2: Se com dois ramos; itens por nó, status sem_itens e contagem nas arestas."""
    from django.utils import timezone

    from apps.execucoes.models import Execucao, ExecucaoNo

    grafo = {
        "versao": 2,
        "nos": [
            {"id": "n1", "tipo": "gatilho", "titulo": "Início", "posicao": {"x": 0, "y": 100}, "config": {}},
            {"id": "n2", "tipo": "se", "titulo": "É grande?", "posicao": {"x": 300, "y": 100}, "config": {}},
            {"id": "n3", "tipo": "saida", "titulo": "Sim", "posicao": {"x": 600, "y": 20}, "config": {}},
            {"id": "n4", "tipo": "saida", "titulo": "Não", "posicao": {"x": 600, "y": 200}, "config": {}},
        ],
        "arestas": [
            {"de": "n1", "saida": 0, "para": "n2", "entrada": 0},
            {"de": "n2", "saida": 0, "para": "n3", "entrada": 0},
            {"de": "n2", "saida": 1, "para": "n4", "entrada": 0},
        ],
        "notas": [],
        "dados_fixos": {},
    }
    exe = Execucao.objects.create(
        fluxo=None, fluxo_nome="Ramos", grafo_snapshot=grafo, executado_por=usuario_coordenador,
        status="sucesso", finalizada_em=timezone.now(),
        arestas=[
            {"de": "n1", "saida": 0, "para": "n2", "entrada": 0, "itens": 3},
            {"de": "n2", "saida": 0, "para": "n3", "entrada": 0, "itens": 3},
            {"de": "n2", "saida": 1, "para": "n4", "entrada": 0, "itens": 0},
        ],
    )
    for ordem, (no_id, tipo, titulo, status, ent, sai) in enumerate(
        [("n1", "gatilho", "Início", "sucesso", 0, 3), ("n2", "se", "É grande?", "sucesso", 3, 3),
         ("n3", "saida", "Sim", "sucesso", 3, 3), ("n4", "saida", "Não", "sem_itens", 0, 0)], start=1
    ):
        ExecucaoNo.objects.create(
            execucao=exe, no_id=no_id, no_tipo=tipo, no_titulo=titulo, ordem=ordem, status=status,
            entrada=[{"json": {"a": "<i>x</i>"}}] * min(ent, 2), saida=[{"json": {"a": 1}}] * min(sai, 2),
            itens_entrada=ent, itens_saida=sai, saidas_contagem=[3, 0] if tipo == "se" else [sai],
        )
    return exe


def test_detalhe_v2_mostra_itens_ramos_e_estados(cliente_coordenador, execucao_v2):
    resposta = cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": execucao_v2.pk}))
    assert "execucoes/detalhe.html" in nomes(resposta)
    html = resposta.content.decode()
    assert "3 → 3 itens" in html and "0 → 0 itens" in html
    assert "Itens por saída: 3 · 0" in html
    assert "não recebeu itens" in html
    assert 'id="nos-execucao"' in html and 'id="grafo-execucao"' in html
    assert "<i>x</i>" not in html



def test_detalhe_de_teste_avisa_que_e_privado(cliente_coordenador, execucao_v2):
    execucao_v2.teste = True
    execucao_v2.save()
    html = cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": execucao_v2.pk})).content.decode()
    assert "Execução de teste" in html
