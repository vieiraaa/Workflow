"""Aceite M5 parte A: expressões. MV2-10 (linguagem, limites, proibições), MV2-11 (variáveis e lista branca), MV2-12 L8–L11.

Cada caso roda um Editar campos (NOV-03) com um campo `r` e lê ExecucaoNo.saida[0]["json"]["r"] (MV2-12 L13).
Entrada padrão do nó "Dados": {"n": 5, "nome": "Ana", "lista": [10,20,30], "obj": {"k": "v"}, "txt": "Olá"}.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

SP = ZoneInfo("America/Sao_Paulo")


# ---------------- MV2-10 · sintaxe {{ }} e "=" ----------------

def test_template_com_texto_fora_da_expressao(avaliar):
    """MV2-10: {{ expr }} com texto fora vira string."""
    assert avaliar("Olá {{ $json.nome }}, você tem {{ $json.n }} itens.") == "Olá Ana, você tem 5 itens."


def test_prefixo_igual_o_resto_e_template(avaliar):
    """MV2-10/L8a: campo que começa com '=' (convenção n8n importada): '={{ x }}' e '=texto {{ x }}'."""
    assert avaliar("={{ $json.n }}", "numero") == 5
    assert avaliar("=Olá {{ $json.nome }}") == "Olá Ana"


def test_expressao_unica_devolve_valor_tipado(avaliar):
    """MV2-10/L8b: exatamente um {{ expr }} devolve número/lista/objeto; com texto fora vira string."""
    assert avaliar("{{ $json.n + 1 }}", "numero") == 6
    assert avaliar("{{ $json.lista }}", "lista") == [10, 20, 30]
    assert avaliar("{{ $json.obj }}", "objeto") == {"k": "v"}
    assert avaliar("v={{ $json.lista }}") == "v=[10,20,30]"
    assert avaliar("v={{ $json.obj }}") == 'v={"k":"v"}'


def test_nulo_e_indefinido_viram_vazio_no_texto(avaliar):
    """MV2-10/L8b+d: null e campo inexistente em texto = '' (sem erro)."""
    assert avaliar("a{{ null }}b") == "ab"
    assert avaliar("a{{ $json.nao_existe }}b") == "ab"


def test_texto_sem_expressao_passa_como_esta(avaliar):
    """MV2-10: texto sem {{ }} não é alterado."""
    assert avaliar("só texto, 100% literal") == "só texto, 100% literal"


@pytest.mark.parametrize("expr,esperado", [
    ("1 + 2", 3), ("7 - 10", -3), ("3 * 4", 12), ("7 / 2", 3.5), ("4 / 2", 2), ("7 % 3", 1),
    ("1 == '1'", True), ("1 === '1'", False), ("1 != '1'", False), ("1 !== '1'", True),
    ("2 < 3", True), ("3 <= 3", True), ("3 > 4", False), ("3 >= 4", False),
    ("true && false", False), ("0 || 'x'", "x"), ("'a' && 'b'", "b"), ("!0", True), ("!'a'", False),
    ("null ?? 'padrao'", "padrao"), ("0 ?? 5", 0), ("'' ?? 'x'", ""),
    ("1 < 2 ? 'sim' : 'nao'", "sim"), ("1 > 2 ? 'sim' : 'nao'", "nao"),
    ("'a' + 1", "a1"), ("'1' + 2", "12"), ("1 + 2 * 3", 7), ("(1 + 2) * 3", 9),
    ("true", True), ("false", False), ("'aspas simples'", "aspas simples"), ('"aspas duplas"', "aspas duplas"),
    ("`x${$json.n}y`", "x5y"), ("[1, 2, 3]", [1, 2, 3]), ("[]", []),
    ("$json.lista[1]", 20), ("$json.obj.k", "v"), ("$json['obj']['k']", "v"), ("$json.lista[0] + $json.lista[2]", 40),
])
def test_operadores_e_literais(expr, esperado, avaliar):
    """MV2-10/L8e: operadores e literais com semântica JavaScript."""
    tipo = "booleano" if isinstance(esperado, bool) else "numero" if isinstance(esperado, int | float) else \
        "lista" if isinstance(esperado, list) else "texto"
    assert avaliar("{{ " + expr + " }}", tipo) == esperado


def test_nulo_literal_e_objeto_literal(avaliar):
    """MV2-10: objeto literal dentro de chamada permitida; null literal."""
    assert avaliar("{{ JSON.stringify({a: $json.n, b: [1, 'x'], c: null}) }}") == '{"a":5,"b":[1,"x"],"c":null}'
    assert avaliar("{{ JSON.stringify({ 'k': true }) }}") == '{"k":true}'


# ---------------- MV2-11 · lista branca ----------------

@pytest.mark.parametrize("expr,esperado", [
    ("'ABC'.toLowerCase()", "abc"), ("'abc'.toUpperCase()", "ABC"), ("'  a b '.trim()", "a b"),
    ("'a,b,c'.split(',')", ["a", "b", "c"]), ("'aXaX'.replace('a', 'b')", "bXaX"),
    ("'abc'.includes('b')", True), ("'abc'.includes('z')", False), ("'abc'.startsWith('ab')", True),
    ("'abc'.endsWith('bc')", True), ("'abcdef'.slice(1, 3)", "bc"), ("'5'.padStart(3, '0')", "005"),
    ("'abc'.length", 3), ("$json.lista.length", 3), ("['a', 'b'].join('-')", "a-b"), ("[1, 2].includes(2)", True),
    ("[1, 2, 3].slice(1)", [2, 3]), ("[1, 2, 3].indexOf(3)", 2), ("[1, 2, 3].indexOf(9)", -1),
    ("Number('42')", 42), ("String(5)", "5"), ("parseInt('42px')", 42), ("parseFloat('3.5')", 3.5),
    ("Math.round(2.4)", 2), ("Math.floor(2.9)", 2), ("Math.ceil(2.1)", 3), ("Math.abs(-3)", 3),
    ("Math.min(4, 2, 9)", 2), ("Math.max(4, 2, 9)", 9),
    ("JSON.stringify({a: 1})", '{"a":1}'), ("JSON.parse('{\"a\": 7}').a", 7),
    ("Object.keys($json.obj)", ["k"]), ("Object.values($json.obj)", ["v"]),
    ("Boolean(0)", False), ("Boolean('x')", True), ("isNaN('abc')", True), ("isNaN(3)", False),
    ("encodeURIComponent('a b&c/ç')", "a%20b%26c%2F%C3%A7"),
])
def test_lista_branca_de_funcoes_e_metodos(expr, esperado, avaliar):
    """MV2-11: cada função/método da lista branca funciona como no JavaScript."""
    tipo = "booleano" if isinstance(esperado, bool) else "numero" if isinstance(esperado, int | float) else \
        "lista" if isinstance(esperado, list) else "texto"
    assert avaliar("{{ " + expr + " }}", tipo) == esperado


# ---------------- MV2-11 · variáveis ----------------

def test_variaveis_de_entrada(avaliar):
    """MV2-11: $json, $input.item/.first()/.last()/.all(), $itemIndex."""
    ent = [{"x": 1}, {"x": 2}, {"x": 3}]
    assert avaliar("{{ $json.x }}", "numero", ent) == 1
    assert avaliar("{{ $input.item.json.x }}", "numero", ent) == 1
    assert avaliar("{{ $input.first().json.x }}", "numero", ent) == 1
    assert avaliar("{{ $input.last().json.x }}", "numero", ent) == 3
    assert avaliar("{{ $input.all().length }}", "numero", ent) == 3
    assert avaliar("{{ $input.all()[1].json.x }}", "numero", ent) == 2
    assert avaliar("{{ $itemIndex }}", "numero", ent) == 0


def test_item_index_acompanha_cada_item(executar, cliente_adm, cadeia2_dados, no, jsons):
    """MV2-11: $itemIndex = posição do item atual (0, 1, 2) e $json muda por item."""
    _, e, _ = executar(cliente_adm, cadeia2_dados("{{ $itemIndex }}", "numero", [{"x": "a"}, {"x": "b"}, {"x": "c"}]))
    assert [j["r"] for j in jsons(no(e, "calc"))] == [0, 1, 2]


def test_referencia_a_outro_no_pelo_titulo(avaliar, executar, cliente_adm, h, no, jsons):
    """MV2-11/L9: $('Título').first()/.last()/.all()/.item; .item = item de mesmo índice (ou o último)."""
    ent = [{"x": 1}, {"x": 2}, {"x": 3}]
    assert avaliar("{{ $('Dados').first().json.x }}", "numero", ent) == 1
    assert avaliar("{{ $('Dados').last().json.x }}", "numero", ent) == 3
    assert avaliar("{{ $('Dados').all().length }}", "numero", ent) == 3
    assert avaliar("{{ $('Início').first().json.executado_por.length > 0 }}", "booleano", ent) is True
    # .item pareia pelo índice: em cada item do nó atual, o item de mesmo índice do nó citado
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("calc", "editar_campos", h.cfg_editar([("r", "{{ $('Dados').item.json.x }}", "numero")]), x=2, titulo="Calc"),
                  dados_fixos={"d": h.itens({"x": 10}, {"x": 20}, {"x": 30})})
    _, e, _ = executar(cliente_adm, g)
    assert [j["r"] for j in jsons(no(e, "calc"))] == [10, 20, 30]


def test_variaveis_de_contexto(executar, cliente_adm, usuario_adm, cadeia2_dados, no, jsons):
    """MV2-11: $execution.id, $workflow.name, $usuario.email, $parametros vazio no M5."""
    def valor(expr, tipo="texto"):
        _, e, f = executar(cliente_adm, cadeia2_dados(expr, tipo))
        assert e.status == "sucesso", e.erro_resumo
        return jsons(no(e, "calc"))[0]["r"], e, f
    r, e, _ = valor("{{ $execution.id }}")
    assert str(r) == str(e.pk)
    r, _, f = valor("{{ $workflow.name }}")
    assert r == f.nome
    r, _, _ = valor("{{ $usuario.email }}")
    assert r == usuario_adm.email
    r, _, _ = valor("{{ Object.keys($parametros).length }}", "numero")
    assert r == 0


ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-03:00$")


def test_now_e_today_no_fuso_de_sao_paulo(avaliar):
    """MV2-11/L10: toISO no padrão Luxon com -03:00; toFormat; $today = início do dia."""
    agora = datetime.now(SP)
    iso = avaliar("{{ $now.toISO() }}")
    assert ISO.match(iso)
    assert abs(datetime.fromisoformat(iso) - agora) < timedelta(seconds=60)
    assert avaliar("{{ $now.toFormat('yyyy') }}") == f"{agora.year:04d}"
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", avaliar("{{ $now.toFormat('yyyy-MM-dd HH:mm:ss') }}"))
    hoje = avaliar("{{ $today.toISO() }}")
    assert hoje.endswith("T00:00:00.000-03:00") and hoje[:10] == agora.strftime("%Y-%m-%d")
    assert abs(avaliar("{{ $now.toMillis() }}", "numero") - agora.timestamp() * 1000) < 60_000


def test_aritmetica_de_datas(avaliar):
    """MV2-11: plus/minus/startOf/toMillis."""
    agora = datetime.now(SP)
    dif = avaliar("{{ $now.plus({hours: 1, minutes: 30}).toMillis() - $now.toMillis() }}", "numero")
    assert abs(dif - 5_400_000) < 5_000
    assert abs(avaliar("{{ $now.minus({days: 1}).toMillis() - $now.toMillis() }}", "numero") + 86_400_000) < 5_000
    assert avaliar("{{ $now.startOf('day').toFormat('HH:mm:ss') }}") == "00:00:00"
    assert avaliar("{{ $now.startOf('month').toFormat('yyyy-MM-dd') }}") == agora.strftime("%Y-%m-01")
    amanha = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
    assert avaliar("{{ $now.plus({days: 1}).toFormat('yyyy-MM-dd') }}") in (amanha, (agora + timedelta(days=2)).strftime("%Y-%m-%d"))


# ---------------- MV2-10 · erros, proibições e limites ----------------

def test_erro_de_expressao_tem_categoria_e_trecho(executar_expr):
    """MV2-10: propriedade de undefined → erro do nó categoria 'expressao' com o trecho; execução erro."""
    e, n = executar_expr("{{ $json.nao_existe.x }}")
    assert e.status == "erro" and n.status == "erro" and n.erro_categoria == "expressao"
    assert "nao_existe" in n.erro_mensagem


def test_sintaxe_invalida_e_erro_expressao(executar_expr):
    """MV2-10: expressão malformada → 'expressao', nunca 500."""
    for expr in ("{{ 1 + }}", "{{ ( }}", "{{ $json. }}", "{{ 'aberta }}"):
        e, n = executar_expr(expr)
        assert e.status == "erro" and n.erro_categoria == "expressao", expr


@pytest.mark.parametrize("expr", [
    "$json.n = 1", "$json.n += 1", "n = 5", "function(){ return 1 }()", "(() => 1)()", "x => x", "new Date()", "this", "this.constructor",
    "$json.__proto__", "$json['__proto__']", "$json.constructor", "$json.constructor.constructor('return 1')()",
    "$json.obj.prototype", "$json['constr' + 'uctor']", "'abc'.constructor", "[].constructor.constructor('return process')()",
    "for (;;) {}", "while (true) {}", "require('fs')", "process.env.HOME", "globalThis", "eval('1')", "import('fs')",
    "$json.lista.map(String)", "$json.lista.filter(Boolean)", "$json.lista.reduce(Math.max)", "$json.lista.forEach(String)",
    "'a'.constructor", "$json.nome.toString.call(1)", "$json.lista.sort()", "Math.random.constructor('return 1')()",
    "Date.now()", "JSON.constructor", "Object.assign({}, $json)", "Object.entries($json)", "setTimeout(1)",
])
def test_construcoes_proibidas_viram_erro_expressao(expr, executar_expr):
    """MV2-10/11: atribuição, function/=>, new, this, laços, __proto__/constructor/prototype e chamadas fora da lista branca → erro 'expressao'."""
    e, n = executar_expr("{{ " + expr + " }}")
    assert e.status == "erro" and n.status == "erro" and n.erro_categoria == "expressao", expr


def test_limite_de_2000_caracteres_por_expressao(executar_expr):
    """MV2-10: expressão de ~2.000 caracteres funciona abaixo do limite e falha acima ('expressao')."""
    dentro = "1" + "+1" * 990  # 1.981 caracteres
    fora = "1" + "+1" * 1010  # 2.021 caracteres
    e, n = executar_expr("{{ " + dentro + " }}", "numero")
    assert e.status == "sucesso" and n.saida[0]["json"]["r"] == 991
    e, n = executar_expr("{{ " + fora + " }}", "numero")
    assert e.status == "erro" and n.erro_categoria == "expressao"


def test_resultado_acima_de_1mb_e_erro_expressao(executar_expr):
    """MV2-10: resultado > 1 MB → erro 'expressao' (nunca estoura memória nem 500)."""
    e, n = executar_expr("{{ 'x'.padStart(2000000, 'x') }}")
    assert e.status == "erro" and n.erro_categoria == "expressao"


def test_mensagem_de_erro_nao_vaza_detalhes_internos(executar_expr):
    """SEG-10 (estendido): a mensagem do erro de expressão não traz traceback nem nomes de módulos do servidor."""
    e, n = executar_expr("{{ $json.nao.x }}")
    m = (n.erro_mensagem or "") + (e.erro_resumo or "")
    assert "Traceback" not in m and ".py" not in m and "line " not in m.lower()


def test_pagecount_e_response_fora_da_paginacao_sao_undefined(avaliar, executar_expr):
    """MV2-14(2): $pageCount/$response fora da paginação = undefined ('' em texto); acessar propriedade = erro 'expressao'."""
    assert avaliar("a{{ $pageCount }}b") == "ab"
    assert avaliar("a{{ $response }}b") == "ab"
    for expr in ("{{ $response.body }}", "{{ $pageCount.x }}"):
        e, n = executar_expr(expr)
        assert e.status == "erro" and n.erro_categoria == "expressao", expr
