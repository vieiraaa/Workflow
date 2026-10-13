"""Aceite M3: placeholders em execução. Fontes: PLH-01..04, EXE-04, SEG-10."""

import json
from datetime import datetime

import pytest

pytestmark = pytest.mark.django_db

# T-060 (migração v2). `{{ anterior.x }}` virou `{{ $json.x }}` com o mesmo significado (MV2-03, MV2-12 L1: o nó HTTP
# roda com resposta_completa=true, então $json = {status, headers, corpo}). Caminho com hífen/índice usa colchetes
# (sintaxe de expressão JavaScript, MV2-10). A saída do nó é a lista de itens (MV2-12 L2/L13) e a requisição resolvida
# fica em requisicoes[] (MV2-15 B10).


def _j(n):
    assert len(n.saida) == 1, n.saida
    return n.saida[0]["json"]


def _rodar(cliente, executar, liberado, cadeia, cfg_http, **cfg2):
    """h1 busca /valores; h2 usa placeholders. Devolve (execucao, eco do h2 ou None)."""
    g = cadeia(cfg_http(f"{liberado.base}/valores"), cfg_http(**cfg2))
    _, e, _ = executar(cliente, g)
    return e


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ $json.num }}", "{{$json.num}}", "{{   $json.num   }}"])
def test_espacos_internos_sao_opcionais(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """PLH-01/MV2-10: espaços internos opcionais. ($json.num é inexistente na saída http → ''; usa status.)"""
    t = template.replace("num", "status")
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "s", "valor": t}])
    assert e.status == "sucesso"
    assert _j(no(e, "h2"))["corpo"]["query"] == {"s": ["200"]}


@pytest.mark.modulo("m3")
def test_anterior_e_a_saida_do_no_imediatamente_anterior(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-02 → $json (MV2-03): $json.status e $json.headers["<nome-minúsculo>"] da saída http; nome com hífen por colchetes."""
    e = _rodar(
        cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco",
        query=[{"nome": "s", "valor": "{{ $json.status }}"}, {"nome": "m", "valor": "{{ $json.headers['x-marcador'] }}"}],
    )
    q = _j(no(e, "h2"))["corpo"]["query"]
    assert q == {"s": ["200"], "m": ["ABC"]}


@pytest.mark.modulo("m3")
def test_caminho_em_json_e_indice_numerico_de_lista(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-01 → MV2-10: $json.corpo.<chave> e índice de lista por colchetes ($json.corpo.lista[1])."""
    e = _rodar(
        cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco",
        query=[{"nome": "a", "valor": "{{ $json.corpo.lista[1] }}"}, {"nome": "b", "valor": "{{ $json.corpo.num }}"}],
    )
    assert _j(no(e, "h2"))["corpo"]["query"] == {"a": ["20"], "b": ["7"]}


@pytest.mark.modulo("m3")
def test_gatilho_como_anterior_do_primeiro_no(cliente_coordenador, usuario_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-02: o primeiro nó http vê a saída do gatilho (executado_por, disparado_em)."""
    g = cadeia(cfg_http(f"{liberado.base}/eco", query=[{"nome": "quem", "valor": "{{ $json.executado_por }}"}, {"nome": "quando", "valor": "{{ $json.disparado_em }}"}]))
    _, e, _ = executar(cliente_coordenador, g)
    q = _j(no(e, "h1"))["corpo"]["query"]
    assert q["quem"] == [usuario_coordenador.email]
    datetime.fromisoformat(q["quando"][0])


@pytest.mark.modulo("m3")
def test_caminho_inexistente_vira_texto_vazio_sem_erro(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """MV2-12 L8(d) (SUBSTITUI a PLH-03 do v1, em que caminho inexistente era erro de placeholder): campo inexistente é
    undefined → '' em texto, SEM erro; o nó roda e a requisição sai com o valor vazio."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": "{{ $json.corpo.nao_existe }}"}])
    h2 = no(e, "h2")
    assert e.status == "sucesso" and h2.status == "sucesso"
    assert h2.requisicoes[0]["query"] == [{"nome": "x", "valor": ""}]
    assert liberado.contagem("/eco") == 1


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ $json.corpo.nao_existe.x }}", "{{ $json.corpo.lista[9].x }}", "{{ $json.corpo.nao_existe.a.b }}"])
def test_propriedade_de_undefined_e_erro_de_expressao_com_o_trecho(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """MV2-12 L8(d)/MV2-10 (equivale à PLH-03 do v1, agora com categoria `expressao`): acessar propriedade DE undefined
    → erro do nó categoria expressao, mensagem com o trecho; seguintes nao_executado; nenhuma requisição sai."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": template}])
    h2 = no(e, "h2")
    assert h2.status == "erro" and h2.erro_categoria == "expressao" and h2.erro_mensagem
    assert no(e, "s").status == "nao_executado" and e.status == "erro"
    assert liberado.contagem("/eco") == 0


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ $json.corpo.lista[9] }}", "{{ $json.corpo.lista.abc }}", "{{ $json.corpo.num.x }}", "{{ $json.status.x }}"])
def test_indice_fora_da_lista_e_descida_em_escalar_viram_vazio(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """MV2-12 L8(d) (era PLH-03: categoria placeholder): índice fora da lista ou propriedade de um escalar é undefined
    (semântica JavaScript, L8e) → '' sem erro e sem 500."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": template}])
    h2 = no(e, "h2")
    assert h2.status == "sucesso", h2.erro_mensagem
    assert h2.requisicoes[0]["query"] == [{"nome": "x", "valor": ""}]


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("template", ["{{ __import__('os').system('id') }}", "{{ $json..corpo }}", "{{ $json.__proto__ }}", "{{ $json.constructor }}"])
def test_parser_proprio_nao_executa_codigo_e_falha_como_expressao(cliente_coordenador, liberado, executar, cadeia, cfg_http, no, template):
    """PLH-03 → MV2-10: interpretador próprio, sem eval/exec — chamada fora da lista branca, sintaxe inválida e acesso a
    __proto__/constructor são erro do nó categoria `expressao` (ou, no máximo, vazio): nunca executam e nunca vazam
    objetos do runtime."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": template}])
    h2 = no(e, "h2")
    if h2.status == "sucesso":
        assert h2.requisicoes[0]["query"] == [{"nome": "x", "valor": ""}]
    else:
        assert h2.erro_categoria == "expressao"
    assert "uid=" not in json.dumps(h2.saida or []) and "function" not in json.dumps(h2.saida or []).lower()
    if template.startswith("{{ __import__") or template == "{{ $json..corpo }}":
        assert h2.status == "erro" and h2.erro_categoria == "expressao"


@pytest.mark.modulo("m3")
def test_aritmetica_e_avaliada_pelo_interpretador_proprio(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """MV2-10 (SUBSTITUI o caso `{{ 7*7 }}` da PLH-03 do v1, que exigia NÃO avaliar): operadores aritméticos fazem parte do
    subconjunto de expressões; `{{ 7*7 }}` resulta em '49'. Sem eval: a chamada acima segue erro."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "x", "valor": "{{ 7*7 }}"}])
    assert no(e, "h2").status == "sucesso"
    assert _j(no(e, "h2"))["corpo"]["query"] == {"x": ["49"]}


@pytest.mark.modulo("m3")
def test_url_valor_e_percent_encoded_e_nao_injeta_caminho_nem_query(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: na URL o valor é percent-encoded (não injeta /, ?, #, @)."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco/{{{{ $json.corpo.v }}}}")
    assert e.status == "sucesso"
    eco = _j(no(e, "h2"))["corpo"]
    for simbolo in ("%2F", "%3F", "%23", "%40"):
        assert simbolo in eco["path"], eco["path"]
    assert eco["query"] == {}
    assert eco["path"].count("/") == 2  # "/eco/<valor codificado>"
    assert liberado.contagem("/eco/a/") == 0


@pytest.mark.modulo("m3")
def test_header_com_crlf_vindo_de_placeholder_e_recusado(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: em headers/query CR/LF vindo de placeholder é recusado (categoria placeholder, SEG-16.3) — nenhuma requisição sai."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", headers=[{"nome": "X-V", "valor": "{{ $json.corpo.crlf }}"}])
    assert no(e, "h2").status == "erro" and no(e, "h2").erro_categoria == "placeholder" and e.status == "erro"
    assert liberado.contagem("/eco") == 0
    assert not any("injetado" in str(r["headers"]).lower() for r in liberado.requisicoes)


@pytest.mark.modulo("m3")
def test_query_com_crlf_vindo_de_placeholder_e_recusado(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: CR/LF em valor de query vindo de placeholder é recusado."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "q", "valor": "{{ $json.corpo.crlf }}"}])
    assert no(e, "h2").status == "erro" and no(e, "h2").erro_categoria == "placeholder"
    assert liberado.contagem("/eco") == 0


@pytest.mark.modulo("m3")
def test_corpo_e_escapado_como_string_json(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: no corpo o valor é escapado como string JSON (aspas, barras, quebras não quebram o JSON)."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", metodo="POST", corpo='{"a": "{{ $json.corpo.v }}", "b": "x"}')
    recebido = json.loads(_j(no(e, "h2"))["corpo"]["corpo"])
    assert recebido == {"a": 'a/b?c#d@e f"g\\h', "b": "x"}


@pytest.mark.modulo("m3")
def test_objetos_e_listas_viram_json_compacto(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04: objetos e listas viram JSON compacto (sem espaços)."""
    e = _rodar(
        cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", metodo="POST",
        corpo='{"o": "{{ $json.corpo.obj }}", "l": "{{ $json.corpo.lista }}"}',
        query=[{"nome": "o", "valor": "{{ $json.corpo.obj }}"}],
    )
    eco = _j(no(e, "h2"))["corpo"]
    assert json.loads(eco["corpo"]) == {"o": '{"k":[1,2]}', "l": "[10,20,30]"}
    assert eco["query"] == {"o": ['{"k":[1,2]}']}


@pytest.mark.modulo("m3")
def test_entrada_gravada_ja_tem_placeholders_resolvidos(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """EXE-12 → MV2-15 B10: a requisição gravada (requisicoes[]) do nó tem os placeholders resolvidos."""
    e = _rodar(cliente_coordenador, executar, liberado, cadeia, cfg_http, url=f"{liberado.base}/eco", query=[{"nome": "s", "valor": "{{ $json.status }}"}])
    assert no(e, "h2").requisicoes[0]["query"] == [{"nome": "s", "valor": "200"}]
    assert "{{" not in json.dumps(no(e, "h2").requisicoes[0]["query"])


@pytest.mark.modulo("m3")
def test_placeholder_no_corpo_json_de_texto_resposta_texto(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-02 → MV2-03: $json.corpo de resposta texto é o texto."""
    g = cadeia(cfg_http(f"{liberado.base}/texto"), cfg_http(f"{liberado.base}/eco", query=[{"nome": "t", "valor": "{{ $json.corpo }}"}]))
    _, e, _ = executar(cliente_coordenador, g)
    assert _j(no(e, "h2"))["corpo"]["query"] == {"t": ["texto simples, nao json"]}
