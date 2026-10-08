"""Render da Home (TEL-13/16/17) e dos componentes de indicador/gráfico com contexto sintético (HOM-03..07, HOM-09)."""

import json

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

pytestmark = pytest.mark.modulo("m4")


def pagina(usuario, **extra):
    request = RequestFactory().get("/")
    request.user = usuario
    contexto = {
        "periodo_rotulo": "Últimos 7 dias",
        "periodos": [{"rotulo": "24h", "url": "?periodo=24h", "ativo": False}, {"rotulo": "7 dias", "url": "?periodo=7d", "ativo": True}],
        "sem_dados": False,
        "sem_dados_periodo": False,
        "indicadores": [
            {"chave": "execucoes", "rotulo": "Execuções", "valor": "12", "valor_cru": 12, "dependente_periodo": True,
             "variacao": {"texto": "+12%", "valor": 12, "sentido": "alta", "bom": True}},
            {"chave": "execucoes_erro", "rotulo": "Com erro", "valor": "3", "valor_cru": 3, "dependente_periodo": True,
             "variacao": {"texto": "novo", "valor": "", "sentido": "alta", "bom": False}},
            {"chave": "fluxos_ativos", "rotulo": "Fluxos ativos", "valor": "4", "valor_cru": 4, "dependente_periodo": False, "variacao": None},
        ],
        "serie": [
            {"rotulo": "01/10", "inicio": "2026-10-01T00:00:00-03:00", "sucesso": 2, "erro": 1},
            {"rotulo": "02/10", "inicio": "2026-10-02T00:00:00-03:00", "sucesso": 0, "erro": 0},
        ],
        "erros": [{"categoria": "timeout", "rotulo": "Tempo esgotado", "total": 2}],
        "por_setor": None,
        "top_fluxos": [{"pk": 7, "nome": "<b>Pedidos</b>", "execucoes": 5, "taxa_sucesso": "80%", "url": "/fluxos/7/"}],
        "ultimas": [{"pk": 9, "fluxo_nome": "Pedidos", "executado_por_nome": "Ana", "status": "erro", "status_rotulo": "Erro",
                     "iniciada_em": None, "url_detalhe": "/execucoes/9/"}],
        "pode_criar_fluxo": True,
        "url_novo_fluxo": "/fluxos/",
        "url_execucoes": "/execucoes/",
    }
    contexto.update(extra)
    return render_to_string("inicio/inicio.html", contexto, request=request)


def test_home_emite_atributos_do_contrato(usuario_adm):
    html = pagina(usuario_adm)
    assert 'data-indicador="execucoes"' in html and 'data-valor="12"' in html and 'data-variacao="12"' in html
    assert 'data-indicador="execucoes_erro"' in html and 'data-variacao=""' in html
    assert html.count("data-variacao=") == 2  # cartão sem variação não emite o atributo
    assert 'id="home-serie"' in html and 'id="home-erros"' in html and 'id="home-setores"' not in html
    assert 'data-execucao="9"' in html and 'data-fluxo="7"' in html
    assert "Ver dados" in html and 'data-href="/execucoes/9/"' in html


def test_home_escapa_nome_de_fluxo(usuario_adm):
    html = pagina(usuario_adm)
    assert "<b>Pedidos</b>" not in html and "&lt;b&gt;Pedidos&lt;/b&gt;" in html


def test_json_da_serie_valido(usuario_adm):
    html = pagina(usuario_adm)
    bruto = html.split('id="home-serie" type="application/json">')[1].split("</script>")[0]
    assert json.loads(bruto)[0]["sucesso"] == 2


def test_setores_so_quando_enviado(usuario_adm):
    html = pagina(usuario_adm, por_setor=[{"setor": "Geral", "total": 9}])
    assert 'id="home-setores"' in html and "Execuções por setor" in html


def test_estados_vazio_erro_e_sem_dados_no_periodo(usuario_adm):
    assert 'data-estado="vazio"' in pagina(usuario_adm, sem_dados=True)
    assert 'data-estado="erro"' in pagina(usuario_adm, erro_carregar=True)
    html = pagina(usuario_adm, sem_dados_periodo=True, serie=[], erros=[], top_fluxos=[], ultimas=[])
    assert 'data-estado="sem_dados_periodo"' in html and "Sem execuções no período." in html
    assert "Nenhuma execução recente." in html


def test_novo_fluxo_so_para_quem_pode(usuario_base):
    assert "Novo fluxo" in pagina(usuario_base)
    assert "Novo fluxo" not in pagina(usuario_base, pode_criar_fluxo=False, ultimas=[])
