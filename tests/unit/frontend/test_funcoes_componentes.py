"""Render dos componentes das Funções (M7a) com dados de exemplo, sem depender das views."""

import pytest
from django.template.loader import render_to_string

pytestmark = pytest.mark.modulo("m7a")


def funcao(**extra):
    base = {
        "pk": 1, "nome": "Relatório <b>diário</b>", "descricao": "Gera o relatório do dia.", "icone": "bar-chart-3",
        "rascunho": False, "inativa": False, "tem_entradas": True, "ultima": None,
        "url_executar": "/funcoes/1/executar/", "url_editar": "/funcoes/1/editar/",
        "url_publicar": "/funcoes/1/publicar/", "url_alternar": "/funcoes/1/alternar/",
    }
    base.update(extra)
    return base


def cartao(f, pode_gerenciar=False):
    return render_to_string("componentes/cartao_funcao.html", {"f": f, "pode_gerenciar": pode_gerenciar})


def test_cartao_escapa_e_oferece_executar_por_link_com_entradas():
    html = cartao(funcao())
    assert "<b>diário</b>" not in html and "&lt;b&gt;" in html
    assert 'href="/funcoes/1/executar/"' in html and "Você ainda não executou" in html
    assert "Editar" not in html and "Rascunho" not in html


def test_cartao_sem_entradas_executa_por_post():
    html = cartao(funcao(tem_entradas=False))
    assert 'method="post" action="/funcoes/1/executar/"' in html


def test_cartao_adm_tem_menu_e_chips():
    html = cartao(funcao(rascunho=True, inativa=True), pode_gerenciar=True)
    assert "Rascunho" in html and "Inativa" in html
    assert "Publicar nova versão" in html and "Ativar" in html and "/funcoes/1/editar/" in html


def test_cartao_mostra_ultima_execucao():
    html = cartao(funcao(ultima={"quando": "há 3 h", "status": "sucesso", "rotulo": "Sucesso", "url": "/funcoes/execucoes/9/"}))
    assert "há 3 h" in html and "Ver resultado" in html and "/funcoes/execucoes/9/" in html


def test_campo_funcao_cada_tipo_e_erro():
    def campo(**kw):
        c = {"nome": "dia", "rotulo": "Dia", "tipo": "texto", "valor": "", "opcoes": [], "obrigatoria": True, "erro": ""}
        c.update(kw)
        return render_to_string("componentes/campo_funcao.html", {"c": c})

    assert 'type="date"' in campo(tipo="data")
    assert 'inputmode="decimal"' in campo(tipo="numero")
    assert "<select" in campo(tipo="lista", opcoes=["a", "b"]) and 'value="a"' in campo(tipo="lista", opcoes=["a"])
    assert 'type="checkbox"' in campo(tipo="booleano")
    erro = campo(erro="Preencha Dia.")
    assert "Preencha Dia." in erro and 'aria-invalid="true"' in erro
    assert "&lt;i&gt;" in campo(valor="<i>")


def test_resultado_tabela_erro_e_truncamento():
    ctx = {
        "funcao": {"nome": "F", "icone": "zap"}, "execucao": {"status": "sucesso", "status_rotulo": "Sucesso", "funcao_versao": 2},
        "parametros": [{"rotulo": "Dia", "valor": "2026-10-13"}], "colunas": ["id", "nome"],
        "linhas": [["1", "<script>x</script>"]], "total_itens": 300, "erro": None,
        "url_detalhe": None, "url_executar_de_novo": "/funcoes/1/executar/?dia=1",
    }
    html = render_to_string("funcoes/resultado.html", ctx)
    assert "&lt;script&gt;" in html and "<script>x" not in html
    assert "Mostrando 1 de 300 itens" in html and "Executar de novo" in html and "Detalhe técnico" not in html
    ctx.update(erro={"categoria": "http", "mensagem": "Falhou"}, colunas=[], linhas=[], execucao={"status": "erro", "status_rotulo": "Erro"}, url_detalhe="/execucoes/1/")
    html = render_to_string("funcoes/resultado.html", ctx)
    assert 'data-estado="erro_execucao"' in html and "Falhou" in html and "Detalhe técnico" in html
