"""T-064: ligação repetida (MV2-24 c) e corpo cortado no limite lido (MV2-24 d, SEG-07)."""

import copy

import pytest

from apps.fluxos import demo
from apps.fluxos.grafo import normalizar, validar
from apps.motor.expressoes import CorpoCortado, ErroRespostaGrande, Escopo, resolver_valor

pytestmark = pytest.mark.modulo("m5")


def test_ligacao_repetida_vira_pendencia_e_padrao_e_zero():
    grafo = copy.deepcopy(demo.grafo_exemplo())
    grafo["arestas"].append({"de": "n1", "para": "n2"})  # sem saida/entrada: padrão 0
    erros, pendencias = validar(grafo)
    assert erros == []
    assert [p["mensagem"] for p in pendencias].count("Ligação repetida.") == 1
    assert all(a["saida"] == 0 and a["entrada"] == 0 for a in normalizar(grafo)["arestas"])


def test_usar_corpo_cortado_levanta_resposta_grande():
    escopo = Escopo(item={"json": {"corpo": CorpoCortado("abc")}}, indice=0)
    with pytest.raises(ErroRespostaGrande) as erro:
        resolver_valor("{{ $json.corpo }}", escopo)
    assert erro.value.categoria == "resposta_grande"


def test_corpo_inteiro_nao_levanta():
    escopo = Escopo(item={"json": {"corpo": "abc"}}, indice=0)
    assert resolver_valor("{{ $json.corpo }}", escopo) == "abc"
