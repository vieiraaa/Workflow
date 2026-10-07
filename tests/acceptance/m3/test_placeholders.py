"""Aceite M3: placeholders em execução. Fontes: PLH-01..04, EXE-04, SEG-10."""

import json
from datetime import datetime

import pytest

pytestmark = pytest.mark.django_db


def _rodar(cliente, executar, liberado, cadeia, cfg_http, **cfg2):
    """h1 busca /valores; h2 usa placeholders. Devolve (execucao, eco do h2 ou None)."""
    g = cadeia(cfg_http(f"{liberado.base}/valores"), cfg_http(**cfg2))
    _, e, _ = executar(cliente, g)
    return e


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ anterior.num }}", "{{anterior.num}}", "{{   anterior.num   }}"])
def test_espacos_internos_sao_opcionais(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """PLH-01: espaços internos opcionais. (anterior.num é inexistente na saída http → erro de placeholder; usa status.)"""
    t = template.replace("num", "status")
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "s", "valor": t}])
    assert e.status == "sucesso"
    assert no(e, "h2").saida["corpo"]["query"] == {"s": ["200"]}


@pytest.mark.modulo("m3")
def test_anterior_e_a_saida_do_no_imediatamente_anterior(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-02: anterior.status e anterior.headers.<nome-minúsculo> da saída http; segmentos com hífen."""
    e = _rodar(
        cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco",
        query=[{"nome": "s", "valor": "{{ anterior.status }}"}, {"nome": "m", "valor": "{{ anterior.headers.x-marcador }}"}],
    )
    q = no(e, "h2").saida["corpo"]["query"]
    assert q == {"s": ["200"], "m": ["ABC"]}


@pytest.mark.modulo("m3")
def test_caminho_em_json_e_indice_numerico_de_lista(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-01: corpo.<chave> e segmento numérico indexa lista."""
    e = _rodar(
        cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco",
        query=[{"nome": "a", "valor": "{{ anterior.corpo.lista.1 }}"}, {"nome": "b", "valor": "{{ anterior.corpo.num }}"}],
    )
    assert no(e, "h2").saida["corpo"]["query"] == {"a": ["20"], "b": ["7"]}


@pytest.mark.modulo("m3")
def test_gatilho_como_anterior_do_primeiro_no(cliente_coordenador, usuario_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-02: o primeiro nó http vê a saída do gatilho (executado_por, disparado_em)."""
    g = cadeia(cfg_http(f"{liberado.base}/eco", query=[{"nome": "quem", "valor": "{{ anterior.executado_por }}"}, {"nome": "quando", "valor": "{{ anterior.disparado_em }}"}]))
    _, e, _ = executar(cliente_coordenador, g)
    q = no(e, "h1").saida["corpo"]["query"]
    assert q["quem"] == [usuario_coordenador.email]
    datetime.fromisoformat(q["quando"][0])


@pytest.mark.modulo("m3")
def test_caminho_inexistente_e_erro_de_placeholder_com_o_caminho(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-03: caminho inexistente → erro do nó, categoria placeholder, mensagem com o caminho; seguintes nao_executado."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": "{{ anterior.corpo.nao_existe }}"}])
    h2 = no(e, "h2")
    assert h2.status == "erro" and h2.erro_categoria == "placeholder"
    assert "anterior.corpo.nao_existe" in h2.erro_mensagem
    assert no(e, "s").status == "nao_executado" and e.status == "erro"
    assert liberado.contagem("/eco") == 0


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ anterior.corpo.lista.9 }}", "{{ anterior.corpo.lista.abc }}", "{{ anterior.corpo.num.x }}", "{{ anterior.status.x }}"])
def test_indice_fora_da_lista_e_descida_em_escalar_sao_erro(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """PLH-03: índice fora da lista ou descer num escalar → categoria placeholder (nunca 500)."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": template}])
    assert no(e, "h2").erro_categoria == "placeholder"


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ __import__('os').system('id') }}", "{{ anterior.__class__ }}", "{{ anterior.corpo.__class__.__mro__ }}", "{{ 7*7 }}", "{{ anterior..corpo }}"])
def test_parser_proprio_nao_avalia_expressoes(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """PLH-03: sem eval/exec/engine — expressão fora da sintaxe vira erro de placeholder ou texto literal; nunca avalia."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": template}])
    h2 = no(e, "h2")
    if h2.status == "sucesso":
        assert h2.saida["corpo"]["query"]["x"] == [template]
    else:
        assert h2.erro_categoria == "placeholder"
    assert "49" not in json.dumps(h2.saida or {}) or template != "{{ 7*7 }}"


@pytest.mark.modulo("m3")
def test_url_valor_e_percent_encoded_e_nao_injeta_caminho_nem_query(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: na URL o valor é percent-encoded (não injeta /, ?, #, @)."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco/{{{{ anterior.corpo.v }}}}")
    assert e.status == "sucesso"
    eco = no(e, "h2").saida["corpo"]
    for simbolo in ("%2F", "%3F", "%23", "%40"):
        assert simbolo in eco["path"], eco["path"]
    assert eco["query"] == {}
    assert eco["path"].count("/") == 2  # "/eco/<valor codificado>"
    assert liberado.contagem("/eco/a/") == 0


@pytest.mark.modulo("m3")
def test_header_com_crlf_vindo_de_placeholder_e_recusado(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: em headers/query CR/LF vindo de placeholder é recusado — nenhuma requisição sai."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", headers=[{"nome": "X-V", "valor": "{{ anterior.corpo.crlf }}"}])
    assert no(e, "h2").status == "erro" and e.status == "erro"
    assert liberado.contagem("/eco") == 0
    assert not any("injetado" in str(r["headers"]).lower() for r in liberado.requisicoes)


@pytest.mark.modulo("m3")
def test_query_com_crlf_vindo_de_placeholder_e_recusado(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: CR/LF em valor de query vindo de placeholder é recusado."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "q", "valor": "{{ anterior.corpo.crlf }}"}])
    assert no(e, "h2").status == "erro"
    assert liberado.contagem("/eco") == 0


@pytest.mark.modulo("m3")
def test_corpo_e_escapado_como_string_json(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: no corpo o valor é escapado como string JSON (aspas, barras, quebras não quebram o JSON)."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", metodo="POST", corpo='{"a": "{{ anterior.corpo.v }}", "b": "x"}')
    recebido = json.loads(no(e, "h2").saida["corpo"]["corpo"])
    assert recebido == {"a": 'a/b?c#d@e f"g\\h', "b": "x"}


@pytest.mark.modulo("m3")
def test_objetos_e_listas_viram_json_compacto(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: objetos e listas viram JSON compacto (sem espaços)."""
    e = _rodar(
        cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", metodo="POST",
        corpo='{"o": "{{ anterior.corpo.obj }}", "l": "{{ anterior.corpo.lista }}"}',
        query=[{"nome": "o", "valor": "{{ anterior.corpo.obj }}"}],
    )
    eco = no(e, "h2").saida["corpo"]
    assert json.loads(eco["corpo"]) == {"o": '{"k":[1,2]}', "l": "[10,20,30]"}
    assert eco["query"] == {"o": ['{"k":[1,2]}']}


@pytest.mark.modulo("m3")
def test_entrada_gravada_ja_tem_placeholders_resolvidos(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """EXE-12: a entrada gravada do nó tem os placeholders resolvidos."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "s", "valor": "{{ anterior.status }}"}])
    assert no(e, "h2").entrada["query"] == [{"nome": "s", "valor": "200"}]
    assert "{{" not in json.dumps(no(e, "h2").entrada)


@pytest.mark.modulo("m3")
def test_placeholder_no_corpo_json_de_texto_resposta_texto(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-02: anterior.corpo de resposta texto é o texto."""
    g = cadeia(cfg_http(f"{liberado.base}/texto"), cfg_http(f"{liberado.base}/eco", query=[{"nome": "t", "valor": "{{ anterior.corpo }}"}]))
    _, e, _ = executar(cliente_coordenador, g)
    assert no(e, "h2").saida["corpo"]["query"] == {"t": ["texto simples, nao json"]}
