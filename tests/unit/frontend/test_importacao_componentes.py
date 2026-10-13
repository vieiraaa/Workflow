"""Componentes de importar/exportar (M5): relatório da importação e menu Arquivo."""

import pytest
from django.template.loader import render_to_string

pytestmark = pytest.mark.modulo("m5")

RELATORIO = {
    "importados": ["Buscar <b>x</b>"],
    "ajustes": [{"no": "HTTP", "mensagem": "Escolha a credencial"}],
    "sem_equivalente": [{"no": "Slack", "tipo_n8n": "n8n-nodes-base.slack"}],
    "expressoes_nao_suportadas": [{"no": "Código", "campo": "url", "expressao": "{{ $x.map(a=>a) }}"}],
    "segredos": [{"no": "HTTP", "campo": "headers"}],
    "codigo_desativado": ["Lista de chamados"],
}


def test_relatorio_mostra_as_seis_listas_e_escapa():
    html = render_to_string("componentes/relatorio_importacao.html", {"relatorio": RELATORIO})
    assert "data-relatorio-importacao" in html and "data-dispensar-relatorio" in html
    for trecho in ("Importados", "Precisam de ajuste", "Código desativados", "Sem equivalente",
                   "Expressões não suportadas", "Segredos encontrados", "n8n-nodes-base.slack", "Lista de chamados"):
        assert trecho in html
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_relatorio_ausente_nao_renderiza_nada():
    assert "data-relatorio-importacao" not in render_to_string("componentes/relatorio_importacao.html", {"relatorio": None})


def test_menu_arquivo_so_mostra_o_que_pode():
    html = render_to_string("componentes/menu_arquivo.html", {"url_exportar": "/e/", "pode_importar": False})
    assert 'href="/e/"' in html and "Importar…" not in html and "para n8n" not in html
    assert render_to_string("componentes/menu_arquivo.html", {}).strip() == ""
