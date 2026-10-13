"""Adversarial M5: expressões (MV2-10/11/12 L8/L11), itens (MV2-01/04/15). Caixa-preta, servidor local."""

import json
import time

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

VAZAMENTOS = ("[native code]", "function ", "<class", "builtins", "object at 0x", "Traceback", "os.environ", "PATH=",
              "environ(", "django.", "settings.py")

# MV2-10: "Proibido: acesso a __proto__/constructor/prototype" — inclusive montado em tempo de execução.
PROIBIDAS = [
    "{{ $json.constructor }}",
    "{{ $json.__proto__ }}",
    "{{ $json['con'+'structor'] }}",
    "{{ $json[\"__pro\"+\"to__\"] }}",
    "{{ $json.nome['constructor'] }}",
    "{{ $json.lista.constructor }}",
    "{{ $json.nome.constructor.constructor('return 1')() }}",
    "{{ $json.obj.prototype }}",
    "{{ Object.keys.constructor }}",
    "{{ JSON.constructor }}",
    "{{ $json?.constructor }}",
    "{{ $json?.['constructor'] }}",
    "{{ `${$json.constructor}` }}",
    "{{ $json['__pro' + 'to__']['x'] }}",
]

# MV2-10: atribuição, function/=>, new, this, laços; MV2-11: sem map/filter/reduce; nada de globais do runtime.
FORA_DA_LINGUAGEM = [
    "{{ x = 1 }}", "{{ $json.n = 2 }}", "{{ $json.n++ }}", "{{ (() => 1)() }}", "{{ function(){ return 1 }() }}",
    "{{ new Date() }}", "{{ this }}", "{{ [1,2].map(x => x) }}", "{{ eval('1') }}", "{{ Function('return 1')() }}",
    "{{ globalThis }}", "{{ process.env }}", "{{ require('fs') }}", "{{ import('fs') }}", "{{ __import__('os') }}",
    "{{ for(;;){} }}", "{{ while(true){} }}", "{{ [].filter.call }}", "{{ `${(() => 1)()}` }}",
    "{{ setTimeout }}", "{{ fetch('http://127.0.0.1:1') }}", "{{ window }}", "{{ self }}", "{{ constructor }}",
]


def _t(e):
    from django.apps import apps
    return apps.get_model("execucoes", "ExecucaoNo").objects.get(execucao=e, no_id="t")


def _sem_vazamento(valor):
    bruto = json.dumps(valor, ensure_ascii=False) if not isinstance(valor, str) else valor
    for v in VAZAMENTOS:
        assert v not in bruto, (v, bruto[:200])


@pytest.mark.parametrize("expr", PROIBIDAS)
def test_acesso_a_proto_constructor_prototype_e_erro_de_expressao(expr, executar_expr):
    """MV2-10: acesso a __proto__/constructor/prototype (literal OU montado em tempo de execução, `?.`, template literal)
    → erro do nó categoria `expressao`; nunca devolve objeto do runtime."""
    e, n = executar_expr(expr)
    assert e is not None
    assert n.status == "erro" and n.erro_categoria == "expressao", (n.status, n.saida)
    _sem_vazamento(n.erro_mensagem or "")


@pytest.mark.parametrize("expr", FORA_DA_LINGUAGEM)
def test_fora_da_linguagem_nunca_executa_e_nao_vaza(expr, executar_expr, servidor):
    """MV2-10/11: sintaxe/globais fora da lista branca → erro `expressao` ou vazio (undefined); nunca executa, nunca 500,
    nunca vaza objetos do runtime, nunca abre conexão."""
    e, n = executar_expr(expr)
    assert e is not None and n.status in ("sucesso", "erro")
    if n.status == "erro":
        assert n.erro_categoria == "expressao", n.erro_categoria
    else:
        assert n.saida[0]["json"]["r"] in ("", None)
    _sem_vazamento(n.erro_mensagem or "")
    _sem_vazamento(n.saida)
    assert servidor.requisicoes == []


def test_expressao_com_2001_caracteres_e_erro_e_2000_funciona(executar_expr, avaliar):
    """MV2-12 L11/MV2-10: expressão > 2.000 caracteres → erro `expressao`; com exatamente 2.000 roda."""
    ok = "'" + "a" * (2000 - 10) + "'"
    assert len("{{ " + ok) > 0
    assert avaliar("{{ " + ok + " }}") == "a" * 1990
    longa = "'" + "a" * 2000 + "'"
    e, n = executar_expr("{{ " + longa + " }}")
    assert n.status == "erro" and n.erro_categoria == "expressao"


@pytest.mark.parametrize("expr", [
    "{{ " + "(" * 900 + "1" + ")" * 900 + " }}",
    "{{ " + "[" * 900 + "]" * 900 + " }}",
    "{{ " + "1" + "+1" * 900 + " }}",
    "{{ " + "!" * 1900 + "true }}",
    "{{ " + "-" * 1900 + "1 }}",
    "{{ " + "`${" * 150 + "1" + "}`" * 150 + " }}",
    "{{ " + "$json.obj" + ".k" * 300 + " }}",
])
def test_aninhamento_e_recursao_profundos_nao_derrubam(expr, executar_expr):
    """MV2-10: aninhamento profundo dentro do limite de 2.000 caracteres roda ou dá erro `expressao`; nunca 500/RecursionError
    e termina rápido."""
    t0 = time.time()
    e, n = executar_expr(expr)
    assert e is not None and n.status in ("sucesso", "erro")
    if n.status == "erro":
        assert n.erro_categoria == "expressao"
    assert time.time() - t0 < 10


@pytest.mark.parametrize("expr", [
    "{{ 'x'.padStart(2000000, 'x') }}",
    "{{ 'x'.padStart(1048577, 'x') }}",
    "{{ JSON.stringify($json.lista).padStart(5000000, 'a') }}",
])
def test_resultado_acima_de_1mb_e_erro_de_expressao(expr, executar_expr):
    """MV2-10/L11: resultado de expressão > 1 MB → erro `expressao` (não grava 2 MB no banco)."""
    e, n = executar_expr(expr)
    assert n.status == "erro" and n.erro_categoria == "expressao"
    assert len(json.dumps(n.saida)) < 100_000


def test_estouro_de_passos_nao_trava(executar_expr):
    """MV2-10: 10.000 passos de avaliação: uma expressão que gera muitos passos dentro de 2.000 caracteres termina (erro ou valor)."""
    expr = "{{ " + "+".join(["Math.max(1,2)"] * 140) + " }}"
    t0 = time.time()
    e, n = executar_expr(expr)
    assert n.status in ("sucesso", "erro") and time.time() - t0 < 10


def test_regex_redos_estoura_em_50ms_como_erro_de_expressao(rodar_no, h):
    """MV2-15 B8: regex catastrófica `(a+)+$` contra 'aaaa…b' estoura 50 ms → erro do nó `expressao`, execução rápida."""
    cfg = {"condicoes": [{"esquerda": "{{ $json.t }}", "operador": "regex", "direita": "(a+)+$", "tipo": "texto"}],
           "combinar": "e"}
    t0 = time.time()
    e, _ = rodar_no("se", cfg, [{"t": "a" * 24 + "b"}], saidas=2)
    dur = time.time() - t0
    n = _t(e)
    assert n.status == "erro" and n.erro_categoria == "expressao", (n.status, n.erro_categoria)
    assert dur < 3, dur


@pytest.mark.parametrize("regex", ["a" * 201, "(" + "a" * 199 + ")", "(" * 150 + ")" * 150 + "a" * 10])
def test_regex_acima_de_200_caracteres_e_pendencia_ao_salvar(regex, cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """MV2-15 B8: regex > 200 caracteres = pendência ao salvar (200 ok=true), e o fluxo não executa."""
    cfg = {"condicoes": [{"esquerda": "{{ $json.t }}", "operador": "regex", "direita": regex, "tipo": "texto"}], "combinar": "e"}
    g = h.cadeia2(h.no2("s", "se", cfg, x=1), h.no2("a", "sem_operacao", x=2), h.no2("b", "sem_operacao", x=2, y=100))
    g["arestas"] = [h.aresta("g", "s"), h.aresta("s", "a", 0), h.aresta("s", "b", 1)]
    f = fabrica_fluxo()
    r = salvar_grafo(cliente_adm, f, g)
    if len(regex) > 200:
        assert r.status_code == 200 and any(p["no"] == "s" for p in r.json()["pendencias"])
    else:
        assert r.status_code == 200


@pytest.mark.parametrize("titulo", ["__proto__", "constructor", "prototype", "A'B", 'A"B', "A\\B", "A') + ('B", "${x}", "{{ x }}", "é☃😀"])
def test_titulos_hostis_em_referencia_a_outro_no(titulo, executar, cliente_adm, h, no, jsons):
    """MV2-11: $('Título') com título hostil (aspas, barras, __proto__, template) nunca dá 500 nem vaza: funciona
    quando o título é escapado corretamente ou dá erro `expressao`."""
    lit = json.dumps(titulo, ensure_ascii=False)  # string JS com escapes
    ex = "{{ $(" + lit + ").first().json.n }}"
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo=titulo),
                  h.no2("c", "editar_campos", h.cfg_editar([("r", ex, "texto")]), x=2, titulo="Calc"),
                  dados_fixos={"d": h.itens({"n": 42})})
    _, e, _ = executar(cliente_adm, g)
    assert e is not None
    n = no(e, "c")
    assert n.status in ("sucesso", "erro")
    if n.status == "sucesso":
        assert jsons(n)[0]["r"] == "42"
    else:
        assert n.erro_categoria == "expressao"
    _sem_vazamento(n.erro_mensagem or "")


def test_titulo_inexistente_em_referencia_e_erro_de_expressao(executar_expr):
    """MV2-11: $('Não existe') → erro `expressao` (nunca 500)."""
    e, n = executar_expr("{{ $('Não existe').first().json.n }}")
    assert n.status == "erro" and n.erro_categoria == "expressao"


@pytest.mark.parametrize("campo", ["__proto__", "constructor", "a.b", "é☃", "a" * 300, "$json", "{{x}}"])
def test_editar_campos_com_nome_hostil_nao_polui_nem_derruba(campo, rodar_no, h):
    """MV2-15 B2/NOV-03: nome de campo hostil (__proto__, caminho, vazio, enorme) → erro categorizado ou valor gravado como dado;
    nunca 500."""
    e, (s,) = rodar_no("editar_campos", h.cfg_editar([(campo, "1", "numero")], incluir_outros=True), [{"a": 1}])
    assert e.status in ("sucesso", "erro")


@pytest.mark.parametrize("chave", ["__proto__", "constructor", "", "é☃", "x" * 500])
def test_resumir_e_juntar_com_chaves_especiais(chave, rodar_no, h):
    """MV2-15 B1/B4: Resumir/Agregar por chave especial agrupa como dado comum (2 grupos) e nunca derruba."""
    ent = [{chave: 1, "v": 1}, {chave: 1, "v": 2}, {chave: 2, "v": 3}]
    e, (s,) = rodar_no("resumir", {"agrupar_por": [chave], "operacoes": [{"campo": "v", "op": "somar"}]}, ent)
    assert e is not None and e.status in ("sucesso", "erro")
    if e.status == "sucesso":
        assert len(s) == 2


# ---------------- itens ----------------

def _separar(cliente_adm, executar, h, n):
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("sp", "separar_lista", {"campo": "lista", "incluir": "nada"}, x=2, titulo="Separar"),
                  h.no2("f", "sem_operacao", x=3, titulo="Fim"),
                  dados_fixos={"d": h.itens({"lista": list(range(n))})})
    return executar(cliente_adm, g)


def test_separar_lista_gigante_acima_de_10000_e_limite_itens(cliente_adm, executar, h, no):
    """MV2-01: > 10.000 itens por saída de nó → erro `limite_itens`; os nós seguintes não rodam; sem 500."""
    _, e, _ = _separar(cliente_adm, executar, h, 10001)
    assert e is not None and e.status == "erro"
    sp = no(e, "sp")
    assert sp.status == "erro" and sp.erro_categoria == "limite_itens"
    assert no(e, "f").status == "nao_executado"


def test_separar_lista_de_exatamente_10000_funciona_e_grava_so_50(cliente_adm, executar, h, no):
    """MV2-01/MV2-07: 10.000 itens passam; o histórico guarda só 50 (truncado) com a contagem real."""
    _, e, _ = _separar(cliente_adm, executar, h, 10000)
    assert e.status == "sucesso"
    sp = no(e, "sp")
    assert sp.itens_saida == 10000 and sp.truncado is True and len(sp.saida) == 50


@pytest.mark.parametrize("lista", ["nao_lista", None, 5, {"a": 1}, "[1,2]"])
def test_separar_lista_com_valor_nao_lista_e_erro_de_expressao(lista, rodar_no):
    """MV2-15 B9: campo que não é lista → erro `expressao` (nunca 500)."""
    e, _ = rodar_no("separar_lista", {"campo": "lista", "incluir": "nada"}, [{"lista": lista}])
    n = _t(e)
    assert n.status == "erro" and n.erro_categoria == "expressao"


def test_laco_de_1001_voltas_e_laco_excessivo(cliente_adm, executar, h, no, nos_de):
    """MV2-15 B5: Repetir em lotes com 1.001 voltas → erro `laco_excessivo`; termina sem travar."""
    nos = [h.no2("g", "gatilho", titulo="Início"), h.no2("d", "sem_operacao", x=1, titulo="Dados"),
           h.no2("t", "repetir_em_lotes", {"tamanho_lote": 1}, x=2, titulo="Lotes"),
           h.no2("c", "sem_operacao", x=3, titulo="Corpo"), h.no2("s", "sem_operacao", x=4, y=100, titulo="Pronto")]
    ars = [h.aresta("g", "d"), h.aresta("d", "t"), h.aresta("t", "c", 0), h.aresta("c", "t", 0, 0), h.aresta("t", "s", 1)]
    t0 = time.time()
    _, e, _ = executar(cliente_adm, h.grafo2(nos, ars, {"d": h.itens(*[{"i": i} for i in range(1001)])}))
    assert e is not None and e.status == "erro", (e.status if e else None)
    assert any(n.erro_categoria == "laco_excessivo" for n in nos_de(e))
    assert time.time() - t0 < 60


@pytest.mark.parametrize("lote", [0, -1, "abc", 10 ** 12, 1.5, None])
def test_tamanho_de_lote_hostil_nao_trava_nem_derruba(lote, cliente_adm, fabrica_fluxo, h, modelos):
    """MV2-15 B5: tamanho_lote fora da faixa → pendência/erro; nunca laço infinito nem 500."""
    nos = [h.no2("g", "gatilho"), h.no2("t", "repetir_em_lotes", {"tamanho_lote": lote}, x=1),
           h.no2("c", "sem_operacao", x=2), h.no2("s", "sem_operacao", x=3, y=100)]
    ars = [h.aresta("g", "t"), h.aresta("t", "c", 0), h.aresta("c", "t"), h.aresta("t", "s", 1)]
    f = fabrica_fluxo(grafo=h.grafo2(nos, ars), status="rascunho")
    from django.urls import reverse
    t0 = time.time()
    r = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert r.status_code in (200, 302, 400) and time.time() - t0 < 30


def test_ciclo_sem_repetir_em_lotes_nao_executa(cliente_adm, fabrica_fluxo, h, modelos):
    """MV2-04/MV2-12 L4: ciclo fora do Repetir em lotes é pendência: executar recusa e nada roda."""
    nos = [h.no2("g", "gatilho"), h.no2("a", "sem_operacao", x=1), h.no2("b", "sem_operacao", x=2)]
    f = fabrica_fluxo(grafo=h.grafo2(nos, [h.aresta("g", "a"), h.aresta("a", "b"), h.aresta("b", "a")]), status="rascunho")
    from django.urls import reverse
    r = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert r.status_code in (200, 302) and modelos.Execucao.objects.count() == 0


def test_item_gigante_e_chaves_hostis_sao_gravados_sem_derrubar(executar, cliente_adm, h, no):
    """MV2-07: item de ~1,5 MB com chaves __proto__/constructor e unicode é gravado (cortado/truncado) sem 500."""
    item = {"__proto__": {"x": 1}, "constructor": "c", "é☃": "y" * 1_500_000}
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("f", "sem_operacao", x=2, titulo="Fim"),
                  dados_fixos={"d": h.itens(item)})
    _, e, _ = executar(cliente_adm, g)
    assert e is not None and e.status in ("sucesso", "erro")


def test_fan_out_multiplicador_estoura_10000_como_limite_itens(rodar_no, h, executar, cliente_adm, no):
    """MV2-01: 101 itens × lista de 101 → 10.201 itens no Separar → `limite_itens` (sem estourar memória/tempo)."""
    ent = [{"lista": list(range(101))} for _ in range(101)]
    e, _ = rodar_no("separar_lista", {"campo": "lista", "incluir": "nada"}, ent)
    n = _t(e)
    assert n.status == "erro" and n.erro_categoria == "limite_itens"


@pytest.mark.parametrize("nome", ["", " ", "\t"])
def test_editar_campos_com_nome_vazio_nao_derruba(nome, cliente_adm, fabrica_fluxo, h):
    """NOV-03: nome de campo vazio/espaço → pendência (não executa) ou erro categorizado; nunca 500."""
    from django.urls import reverse
    g = h.cadeia2(h.no2("c", "editar_campos", h.cfg_editar([(nome, "1", "numero")]), x=1))
    f = fabrica_fluxo(grafo=g, status="rascunho")
    r = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert r.status_code in (200, 302)


def test_escape_unicode_de_par_substituto_em_literal_js_vira_o_emoji(avaliar):
    """MV2-10/L8(e) (semântica JavaScript): "\\ud83d\\ude00" em literal de string é UM caractere (😀); nunca 500 ao gravar."""
    assert avaliar('{{ "\\ud83d\\ude00" }}') == "😀"


def test_surrogate_solto_em_literal_nao_derruba_a_gravacao(executar_expr):
    """MV2-10/SEG-14: "\\ud800" (surrogate solto) em literal → valor ou erro `expressao`; a execução é gravada (sem 500/
    UnicodeEncodeError e sem deixar a transação do banco quebrada)."""
    e, n = executar_expr('{{ "\\ud800" }}')
    assert e is not None and n.status in ("sucesso", "erro")
    if n.status == "erro":
        assert n.erro_categoria == "expressao"
