"""T-053: interpretador de expressões (MV2-10/11/12 L8–L11). Sem banco."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.motor.expressoes import (
    ErroExpressao,
    Escopo,
    resolver_texto,
    resolver_valor,
)

pytestmark = pytest.mark.modulo("m5")
SP = ZoneInfo("America/Sao_Paulo")
DADOS = {"n": 5, "nome": "Ana", "lista": [10, 20, 30], "obj": {"k": "v"}, "txt": "Olá"}


def _escopo(**extra):
    itens = [{"json": DADOS}]
    resultados = {"Dados": itens, "Vazio": []}
    return Escopo(item=itens[0], indice=0, entrada=itens, resultados=resultados, **extra)


def _v(expr, **extra):
    return resolver_valor("{{ " + expr + " }}", _escopo(**extra))


@pytest.mark.parametrize(
    "expr,esperado",
    [
        ("1 + 2", 3),
        ("7 / 2", 3.5),
        ("4 / 2", 2),
        ("7 % 3", 1),
        ("-7 % 3", -1),
        ("1 == '1'", True),
        ("1 === '1'", False),
        ("null == undefined", True),
        ("null === undefined", False),
        ("true == 1", True),
        ("[] == 0", True),
        ("0 || 'x'", "x"),
        ("'' ?? 'x'", ""),
        ("null ?? 'p'", "p"),
        ("!0", True),
        ("[] ? 'sim' : 'nao'", "sim"),
        ("{} ? 1 : 2", 1),
        ("'' ? 1 : 2", 2),
        ("'a' < 'b'", True),
        ("'10' < '9'", True),
        ("10 < '9'", False),
        ("1 + '2'", "12"),
        ("'3' * '4'", 12),
        ("'a' * 2", None),
        ("[1, 2] + ''", "1,2"),
        ("$json.lista[1] + $json.lista[2]", 50),
        ("$json?.obj?.k", "v"),
        ("$json.nada?.x", None),
        ("$json.obj['k']", "v"),
        ("`${$json.n}-${$json.nome}`", "5-Ana"),
        ("1 / 0", None),
        ("0 / 0", None),
        ("2 * 3 + 4", 10),
        ("2 * (3 + 4)", 14),
        ("'ab'.toUpperCase().toLowerCase()", "ab"),
        ("'a-b'.split('-')[1]", "b"),
        ("'abc'.slice(-2)", "bc"),
        ("'abcdef'.slice(1, -1)", "bcde"),
        ("[1,2,3].slice(-1)", [3]),
        ("Math.round(2.5)", 3),
        ("Math.round(-2.5)", -2),
        ("Math.max()", None),
        ("parseInt('abc')", None),
        ("parseFloat('1.5e1x')", 15),
        ("Number('')", 0),
        ("Number(' 7 ')", 7),
        ("Number('x')", None),
        ("String(null)", "null"),
        ("String([1,[2,3]])", "1,2,3"),
        ("JSON.stringify('a')", '"a"'),
        ("JSON.stringify([undefined, NaN])", "[null,null]"),
        ("Object.keys([5, 6])", ["0", "1"]),
        ("$json.lista.indexOf(20)", 1),
        ("[1, 2].includes('1')", False),
        ("'x'.padStart(3)", "  x"),
        ("'abc'.padStart(2, '0')", "abc"),
        ("encodeURIComponent('a+b')", "a%2Bb"),
        ("isNaN(undefined)", True),
    ],
)
def test_semantica_javascript(expr, esperado):
    assert _v(expr) == esperado


def test_tipado_so_para_uma_expressao_unica_e_texto_caso_contrario():
    escopo = _escopo()
    assert resolver_valor("{{ $json.lista }}", escopo) == [10, 20, 30]
    assert resolver_valor("={{ $json.n }}", escopo) == 5
    assert resolver_valor("={{ $json.n }} itens", escopo) == "5 itens"
    assert resolver_valor("x{{ $json.obj }}", escopo) == 'x{"k":"v"}'
    assert resolver_valor("{{ $json.n }}{{ $json.n }}", escopo) == "55"
    assert resolver_texto("a{{ undefined }}b{{ null }}c", escopo) == "abc"
    assert resolver_texto("{{ true }}/{{ 1.5 }}", escopo) == "true/1.5"
    assert resolver_texto("sem expressão", escopo) == "sem expressão"
    assert resolver_valor("  {{ 1 + 1 }}  ", escopo) == 2


def test_chaves_dentro_da_expressao_e_em_strings():
    escopo = _escopo()
    assert resolver_texto("{{ JSON.stringify({a: {b: 1}}) }}", escopo) == '{"a":{"b":1}}'
    assert resolver_texto("{{ '}}' }}", escopo) == "}}"
    with pytest.raises(ErroExpressao):
        resolver_texto("{{ 1 + 1", escopo)


def test_formatar_recebe_o_valor_ja_como_texto():
    assert resolver_texto("a{{ 'x y' }}b", _escopo(), lambda v: v.replace(" ", "_")) == "ax_yb"


def test_variaveis_de_contexto_e_entrada():
    itens = [{"json": {"x": 1}}, {"json": {"x": 2}}, {"json": {"x": 3}}]
    resultados = {"Dados": itens}
    escopo = Escopo(item=itens[1], indice=1, entrada=itens, resultados=resultados, execucao_id=9,
                    fluxo_nome="F", usuario_email="u@e.test", parametros={"a": 1})  # fmt: skip
    ok = lambda e: resolver_valor("{{ " + e + " }}", escopo)  # noqa: E731
    assert ok("$json.x") == 2 and ok("$itemIndex") == 1
    assert ok("$input.first().json.x") == 1 and ok("$input.last().json.x") == 3
    assert ok("$input.all().length") == 3 and ok("$input.item.json.x") == 2
    assert ok("$('Dados').item.json.x") == 2  # L9: mesmo índice
    assert ok("$('Dados').first().json.x") == 1 and ok("$('Dados').all()[2].json.x") == 3
    assert ok("$execution.id") == 9 and ok("$workflow.name") == "F"
    assert ok("$usuario.email") == "u@e.test" and ok("$parametros.a") == 1
    curto = Escopo(item=itens[2], indice=2, resultados={"X": [{"json": {"v": 7}}]})
    assert resolver_valor("{{ $('X').item.json.v }}", curto) == 7  # menos itens → o último


def test_no_inexistente_e_primeiro_de_lista_vazia():
    with pytest.raises(ErroExpressao):
        _v("$('Nao existe').first()")
    assert _v("$('Vazio').first()") is None
    with pytest.raises(ErroExpressao):
        _v("$('Vazio').first().json")


def test_pagecount_e_response():
    assert _v("$pageCount") is None and _v("$response") is None
    with pytest.raises(ErroExpressao):
        _v("$response.body")
    assert _v("$pageCount", pagina=2) == 2
    assert _v("$response.body.x", resposta={"status": 200, "body": {"x": 1}}) == 1


ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-03:00$")


def test_datas_estilo_luxon():
    agora = datetime(2026, 10, 9, 15, 30, 45, 123000, tzinfo=SP)
    assert _v("$now.toISO()", agora=agora) == "2026-10-09T15:30:45.123-03:00"
    assert _v("$today.toISO()", agora=agora) == "2026-10-09T00:00:00.000-03:00"
    assert _v("$now.toFormat('yyyy-MM-dd HH:mm:ss')", agora=agora) == "2026-10-09 15:30:45"
    assert _v("$now.toFormat('dd/MM/yy h:mm a')", agora=agora) == "09/10/26 3:30 PM"
    assert _v("$now.plus({days: 25}).toFormat('yyyy-MM-dd')", agora=agora) == "2026-11-03"
    assert _v("$now.minus({months: 10}).toFormat('yyyy-MM-dd')", agora=agora) == "2025-12-09"
    assert _v("$now.plus({months: 4}).toISODate()", agora=datetime(2026, 10, 31, tzinfo=SP)) == (
        "2027-02-28"
    )
    assert _v("$now.startOf('month').toFormat('yyyy-MM-dd')", agora=agora) == "2026-10-01"
    assert _v("$now.startOf('week').toFormat('yyyy-MM-dd')", agora=agora) == "2026-10-05"
    assert _v("$now.year", agora=agora) == 2026 and _v("$now.weekday", agora=agora) == 5
    assert _v("$now.plus({hours: 1}).toMillis() - $now.toMillis()", agora=agora) == 3_600_000
    utc = datetime(2026, 10, 9, 18, 0, tzinfo=ZoneInfo("UTC"))
    assert _v("$now.toISO()", agora=utc) == "2026-10-09T15:00:00.000-03:00"
    assert ISO.match(_v("$now.toISO()"))
    assert abs(_v("$now.toMillis()") - datetime.now(SP).timestamp() * 1000) < 60_000
    assert (datetime.fromisoformat(_v("$now.toISO()")) - datetime.now(SP)) < timedelta(seconds=60)


@pytest.mark.parametrize(
    "expr",
    [
        "$json.n = 1", "$json.n += 1", "n++", "x => x", "function(){}()", "(() => 1)()",
        "new Date()",
        "this", "this.constructor", "$json.__proto__", "$json['__proto__']", "$json.constructor",
        "$json['constr' + 'uctor']", "'a'.constructor", "[].constructor.constructor('x')()",
        "for (;;) {}", "while (true) {}", "require('fs')", "process.env", "globalThis", "eval('1')",
        "import('fs')", "$json.lista.map(String)", "$json.lista.filter(Boolean)",
        "$json.lista.reduce(Math.max)", "$json.lista.forEach(String)", "$json.lista.sort()",
        "$json.nome.toString.call(1)", "Math.random.constructor('return 1')()", "Date.now()",
        "JSON.constructor", "Object.assign({}, $json)", "Object.entries($json)", "setTimeout(1)",
        "1 +", "(", "$json.", "'aberta", "1 2", "[1, 2", "{a: 1", "a ? b", "1 @ 2", "typeof 1",
        "$json.nada.x", "undefined.x", "null.x", "(5).toFixed(2)", "$json.obj.hasOwnProperty('k')",
        "'a'.replace(/a/, 'b')", "$('X', 'Y')", "$(1)", "5()", "'x'()", "$json()",
        "'x'.padStart(2000000, 'x')", "('x'.padStart(900000, 'x') + 'x'.padStart(900000, 'x'))",
    ],
)  # fmt: skip
def test_proibido_ou_invalido_vira_erro_expressao(expr):
    with pytest.raises(ErroExpressao) as erro:
        _v(expr)
    texto = str(erro.value)
    assert "Traceback" not in texto and ".py" not in texto


def test_limites():
    assert _v("1" + "+1" * 990) == 991  # ~1.981 caracteres
    with pytest.raises(ErroExpressao):
        _v("1" + "+1" * 1010)
    with pytest.raises(ErroExpressao):
        _v("[" * 200 + "]" * 200)
    with pytest.raises(ErroExpressao):
        _v("(" * 5000 + "1" + ")" * 5000)
    grande = "[" + ", ".join(["'x'"] * 300) + "]"  # 300 elementos: dentro do limite de 2.000 chars
    assert len(_v(grande)) == 300


def test_limite_de_passos(monkeypatch):
    from apps.motor.expressoes import avaliador

    monkeypatch.setattr(avaliador, "MAX_PASSOS", 50)
    with pytest.raises(ErroExpressao):
        _v("1" + "+1" * 100)


def test_mensagem_traz_trecho_e_nao_vaza_detalhes():
    with pytest.raises(ErroExpressao) as erro:
        _v("$json.nao_existe.x")
    assert "nao_existe" in erro.value.mensagem and "line" not in erro.value.mensagem.lower()
    assert erro.value.categoria == "expressao"
