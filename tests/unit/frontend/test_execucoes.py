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
