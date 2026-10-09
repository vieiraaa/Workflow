"""T-055: regex seguro, condições, utilidades e pendências dos nós de dados/fluxo/código."""

import time

import pytest

from apps.fluxos import grafo as grafo_mod
from apps.fluxos.pendencias_nos import pendencias_do_no
from apps.motor.erros import FalhaNo
from apps.motor.expressoes import Escopo
from apps.motor.nos import condicoes, regex, util

pytestmark = pytest.mark.modulo("m5")


# ---------------------------------------------------------------- regex
@pytest.mark.parametrize(
    "padrao", ["^(a+)+$", "(a*)*b", "(a|aa)+$", "(.*a){20}x(.+)+", "^(\\w+\\s?)*$"]
)
def test_regex_catastrofica_e_recusada_sem_executar(padrao):
    inicio = time.monotonic()
    with pytest.raises(FalhaNo) as erro:
        regex.procurar(padrao, "a" * 40 + "!")
    assert erro.value.categoria == "expressao" and time.monotonic() - inicio < 1


@pytest.mark.parametrize("padrao,texto,esperado", [
    ("^[a-z]+\\d+$", "abc123", True), ("^\\d+$", "abc", False), ("(ab)+c", "ababc", True),
    ("a{2,5}", "caab", True), ("^(foo)(bar)$", "foobar", True),
])  # fmt: skip
def test_regex_comum_funciona(padrao, texto, esperado):
    assert regex.procurar(padrao, texto) is esperado


def test_regex_limites_de_tamanho_e_invalida():
    with pytest.raises(FalhaNo):
        regex.procurar("a" * 201, "a")
    with pytest.raises(FalhaNo):
        regex.procurar("(", "a")
    with pytest.raises(FalhaNo):
        regex.procurar("a", "x" * (regex.MAX_TEXTO + 1))


# ---------------------------------------------------------------- condições
def _cond(esq, op, dir_=None, tipo="texto"):
    return {"esquerda": esq, "operador": op, "direita": dir_, "tipo": tipo}


def _ok(condicao, **json_item):
    item = {"json": json_item}
    return condicoes._uma(condicao, Escopo(item=item, entrada=[item]))


def test_direita_literal_e_convertida_pelo_tipo():
    assert _ok(_cond("{{ $json.n }}", "igual", "5", "numero"), n=5)
    assert _ok(_cond("{{ $json.n }}", "maior", "4.5", "numero"), n=5)
    assert _ok(_cond("{{ $json.b }}", "igual", "true", "booleano"), b=True)
    assert not _ok(_cond("{{ $json.t }}", "igual", "2", "numero"), t="3")
    assert _ok(_cond("{{ $json.t }}", "igual", "2", "texto"), t="2")


def test_data_igual_entre_fusos_e_data_so_com_dia():
    c = _cond("{{ $json.d }}", "igual", "2026-10-09T03:00:00Z", "data")
    assert _ok(c, d="2026-10-09T00:00:00.000-03:00")
    assert _ok(_cond("{{ $json.d }}", "menor", "2026-10-10", "data"), d="2026-10-09")


def test_data_invalida_e_erro_do_no():
    with pytest.raises(FalhaNo):
        _ok(_cond("{{ $json.d }}", "igual", "2026-10-09", "data"), d="nao e data")


def test_vazio_existe_e_contem_em_lista_e_objeto():
    assert _ok(_cond("{{ $json.v }}", "vazio", None, "lista"), v=[])
    assert _ok(_cond("{{ $json.v }}", "existe", None, "texto"), v=0)
    assert _ok(_cond("{{ $json.nada }}", "nao_existe", None, "texto"), v=0)
    assert _ok(_cond("{{ $json.v }}", "contem", "2", "lista"), v=[1, 2])
    assert _ok(_cond("{{ $json.v }}", "contem", "k", "objeto"), v={"k": 1})
    assert not _ok(_cond("{{ $json.v }}", "contem", "z", "lista"), v=[1, 2])


def test_operador_ordenado_em_lista_e_erro():
    with pytest.raises(FalhaNo):
        _ok(_cond("{{ $json.v }}", "maior", "1", "lista"), v=[1])


def test_avaliar_condicoes_e_ou():
    item = {"json": {"a": 1, "b": 2}}
    escopo = Escopo(item=item, entrada=[item])
    cs = [
        _cond("{{ $json.a }}", "igual", "1", "numero"),
        _cond("{{ $json.b }}", "igual", "9", "numero"),
    ]
    assert not condicoes.avaliar_condicoes(cs, "e", escopo)
    assert condicoes.avaliar_condicoes(cs, "ou", escopo)


# ---------------------------------------------------------------- utilidades
def test_caminho_obter_definir_remover():
    dados = {"a": {"b": [10, {"c": 1}]}}
    assert util.obter(dados, "a.b.0") == 10 and util.obter(dados, "a.b.1.c") == 1
    assert util.obter(dados, "a.x") is util.AUSENTE and util.obter(dados, "a.b.9") is util.AUSENTE
    novo = {}
    util.definir(novo, "x.y.z", 5)
    assert novo == {"x": {"y": {"z": 5}}}
    util.remover(novo, "x.y.z")
    assert novo == {"x": {"y": {}}} and util.ultimo_segmento("a.b.c") == "c"


def test_para_data_aceita_iso_ms_e_recusa_lixo():
    assert util.para_data("2026-10-09T15:30:00").utcoffset().total_seconds() == -3 * 3600
    assert util.para_data(0).year == 1969
    for ruim in ("lixo", "", None, True, [1]):
        with pytest.raises(FalhaNo):
            util.para_data(ruim)


# ---------------------------------------------------------------- pendências de config
def _no(tipo, **config):
    return {"id": "x", "tipo": tipo, "titulo": "X", "config": config}


@pytest.mark.parametrize("no", [
    _no("se"), _no("filtrar", condicoes=[]), _no("escolher", regras=[]), _no("ordenar"),
    _no("limitar"), _no("limitar", quantidade=-1), _no("separar_lista"), _no("resumir"),
    _no("data_hora"), _no("data_hora", operacao="formatar", campo="d"), _no("editar_campos"),
    _no("repetir_em_lotes"), _no("repetir_em_lotes", tamanho_lote=0), _no("parar_com_erro"),
    _no("codigo"), _no("juntar", entradas=9), _no("juntar", modo="escolher_entrada", entrada=7),
    _no("juntar", modo="combinar_por_campo"), _no("agregar", modo="campos", campos=[]),
    _no("remover_duplicados", comparar="campos", campos=[]),
    _no("se", condicoes=[_cond("", "igual", "1")]),
    _no("se", condicoes=[_cond("{{ $json.a }}", "invalido", "1")]),
    _no("se", condicoes=[_cond("{{ $json.a }}", "igual", None)]),
])  # fmt: skip
def test_config_incompleta_gera_pendencia(no):
    assert pendencias_do_no(no)


@pytest.mark.parametrize("no", [
    _no("se", condicoes=[_cond("{{ $json.a }}", "igual", "1")], combinar="e"),
    _no("se", condicoes=[_cond("{{ $json.a }}", "vazio")]),
    _no("limitar", quantidade=0, de="inicio"),
    _no("data_hora", operacao="agora", saida="r"),
    _no("juntar", modo="anexar", entradas=3),
    _no("codigo", modo="uma_vez_para_todos", codigo="return [{json: {}}];"),
    _no("sem_operacao"), _no("gatilho"), _no("saida"),
])  # fmt: skip
def test_config_completa_nao_gera_pendencia(no):
    assert pendencias_do_no(no) == []


# ---------------------------------------------------------------- Código: só Adm (mexeu_no_codigo)
def _grafo(*nos):
    base = {"versao": 2, "nos": [], "arestas": [], "notas": [], "dados_fixos": {}}
    for id_, tipo, config, desativado in nos:
        base["nos"].append({"id": id_, "tipo": tipo, "titulo": id_, "posicao": {"x": 0, "y": 0},
                            "config": config, "desativado": desativado,
                            "executar_uma_vez": False, "em_erro": "parar"})  # fmt: skip
    return base


def test_mexeu_no_codigo_distingue_adicao_alteracao_e_posicao():
    antes = _grafo(("c", "codigo", {"codigo": "a"}, False), ("g", "gatilho", {}, False))
    assert not grafo_mod.mexeu_no_codigo(antes, grafo_mod.normalizar(antes))
    movido = grafo_mod.normalizar(antes)
    movido["nos"][0]["posicao"] = {"x": 99, "y": 9}
    assert not grafo_mod.mexeu_no_codigo(antes, movido)
    for alterar in (
        lambda g: g["nos"][0]["config"].update(codigo="b"),
        lambda g: g["nos"][0].update(desativado=True),
        lambda g: g["nos"][0].update(tipo="sem_operacao"),
        lambda g: g["nos"].append({**g["nos"][0], "id": "novo"}),
    ):
        novo = grafo_mod.normalizar(antes)
        alterar(novo)
        assert grafo_mod.mexeu_no_codigo(antes, novo)
