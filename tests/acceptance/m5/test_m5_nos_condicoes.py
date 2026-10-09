"""Aceite M5 parte B: catálogo (NOV-01) e condições (NOV-02: Se, Filtrar, Escolher). Chaves: MV2-14(7), MV2-15 B8."""

import time

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

TIPOS = ["gatilho", "http", "codigo", "editar_campos", "filtrar", "se", "escolher", "juntar", "ordenar", "limitar",
         "remover_duplicados", "separar_lista", "agregar", "resumir", "data_hora", "repetir_em_lotes", "parar_com_erro",
         "sem_operacao", "saida"]


@pytest.mark.parametrize("tipo", TIPOS)
def test_catalogo_todos_os_tipos_sao_aceitos(tipo, cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-01: cada tipo do catálogo é um tipo conhecido (nunca 400 de 'tipo desconhecido'; config incompleta = pendência)."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    g = h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("x", tipo, {}, x=1)], [("g", "x")])
    r = salvar_grafo(cliente_adm, f, g)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_tipo_fora_do_catalogo_e_400(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-01/GRF-02: tipo desconhecido continua recusado."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    g = h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("x", "webhook", {}, x=1)], [("g", "x")])
    assert salvar_grafo(cliente_adm, f, g).status_code == 400


def cond(esq, op, dir_=None, tipo="texto"):
    return {"esquerda": esq, "operador": op, "direita": dir_, "tipo": tipo}


def V(campo="v"):
    return "{{ $json." + campo + " }}"


# (tipo, valor do item, operador, direita, esperado)
CASOS = [
    ("texto", "abc", "igual", "abc", True), ("texto", "abc", "igual", "ABC", False), ("texto", "abc", "diferente", "x", True),
    ("texto", "abc", "diferente", "abc", False), ("texto", "abc", "contem", "b", True), ("texto", "abc", "contem", "z", False),
    ("texto", "abc", "nao_contem", "z", True), ("texto", "abc", "nao_contem", "b", False),
    ("texto", "abc", "comeca_com", "ab", True), ("texto", "abc", "comeca_com", "bc", False),
    ("texto", "abc", "termina_com", "bc", True), ("texto", "abc", "termina_com", "ab", False),
    ("texto", "", "vazio", None, True), ("texto", "a", "vazio", None, False),
    ("texto", "a", "nao_vazio", None, True), ("texto", "", "nao_vazio", None, False),
    ("texto", "abc123", "regex", "^[a-z]+\\d+$", True), ("texto", "abc", "regex", "^\\d+$", False),
    ("numero", 5, "maior", "3", True), ("numero", 3, "maior", "3", False), ("numero", 3, "maior_igual", "3", True),
    ("numero", 2, "maior_igual", "3", False), ("numero", 2, "menor", "3", True), ("numero", 3, "menor", "3", False),
    ("numero", 3, "menor_igual", "3", True), ("numero", 4, "menor_igual", "3", False),
    ("numero", 3, "igual", "3", True), ("numero", 3, "diferente", "3", False), ("numero", 3, "diferente", "4", True),
    ("numero", 10, "maior", "9", True),  # numérico, não lexicográfico
    ("booleano", True, "igual", "true", True), ("booleano", False, "igual", "true", False),
    ("booleano", False, "diferente", "true", True),
    ("data", "2026-10-09", "maior", "2026-10-08", True), ("data", "2026-10-09", "menor", "2026-10-08", False),
    ("data", "2026-10-09T00:00:00.000-03:00", "igual", "2026-10-09T03:00:00Z", True),
    ("data", "2026-10-08", "menor_igual", "2026-10-08", True),
    ("lista", ["a", "b"], "contem", "b", True), ("lista", ["a", "b"], "nao_contem", "z", True),
    ("lista", [], "vazio", None, True), ("lista", ["a"], "nao_vazio", None, True), ("lista", ["a"], "vazio", None, False),
    ("objeto", {}, "vazio", None, True), ("objeto", {"a": 1}, "nao_vazio", None, True), ("objeto", {"a": 1}, "vazio", None, False),
]


@pytest.mark.parametrize("tipo,valor,op,direita,esperado", CASOS)
def test_se_operadores_por_tipo(tipo, valor, op, direita, esperado, rodar_no):
    """NOV-02: Se, saída 0 = verdadeiro, saída 1 = falso, para cada operador/tipo."""
    e, (verd, falso) = rodar_no("se", {"condicoes": [cond(V(), op, direita, tipo)], "combinar": "e"}, [{"v": valor}], saidas=2)
    assert e.status == "sucesso", e.erro_resumo
    assert (verd, falso) == (([{"v": valor}], []) if esperado else ([], [{"v": valor}]))


def test_existe_e_nao_existe(rodar_no):
    """NOV-02: existe / nao_existe sobre campo presente e ausente (undefined)."""
    ent = [{"campo": 1, "id": 1}, {"id": 2}]
    _, (v, f) = rodar_no("se", {"condicoes": [cond(V("campo"), "existe", None, "texto")], "combinar": "e"}, ent, 2)
    assert [j["id"] for j in v] == [1] and [j["id"] for j in f] == [2]
    _, (v, f) = rodar_no("se", {"condicoes": [cond(V("campo"), "nao_existe", None, "texto")], "combinar": "e"}, ent, 2)
    assert [j["id"] for j in v] == [2] and [j["id"] for j in f] == [1]


def test_se_roteia_cada_item_individualmente(rodar_no):
    """NOV-02/MV2-01: cada item vai para a saída certa, mantendo a ordem."""
    ent = [{"n": 1}, {"n": 10}, {"n": 2}, {"n": 20}]
    _, (v, f) = rodar_no("se", {"condicoes": [cond("{{ $json.n }}", "maior", "5", "numero")], "combinar": "e"}, ent, 2)
    assert [j["n"] for j in v] == [10, 20] and [j["n"] for j in f] == [1, 2]


def test_combinar_e_ou(rodar_no):
    """NOV-02: condições combinadas por 'e' e por 'ou'."""
    ent = [{"a": 1, "b": 1}, {"a": 1, "b": 2}, {"a": 2, "b": 2}]
    cs = [cond("{{ $json.a }}", "igual", "1", "numero"), cond("{{ $json.b }}", "igual", "1", "numero")]
    _, (v, f) = rodar_no("se", {"condicoes": cs, "combinar": "e"}, ent, 2)
    assert v == [ent[0]] and f == [ent[1], ent[2]]
    _, (v, f) = rodar_no("se", {"condicoes": cs, "combinar": "ou"}, ent, 2)
    assert v == [ent[0], ent[1]] and f == [ent[2]]


def test_condicao_com_expressao_na_direita(rodar_no):
    """NOV-02: direita também aceita expressão ({{ }}), tipada."""
    ent = [{"a": 5, "limite": 5}, {"a": 5, "limite": 9}]
    _, (v, f) = rodar_no("se", {"condicoes": [cond(V("a"), "igual", V("limite"), "numero")], "combinar": "e"}, ent, 2)
    assert v == [ent[0]] and f == [ent[1]]


def test_filtrar_passa_so_o_que_atende(rodar_no):
    """NOV-02: Filtrar mantém só os itens que atendem."""
    ent = [{"s": "ok", "i": 1}, {"s": "no", "i": 2}, {"s": "ok", "i": 3}]
    cfg = {"condicoes": [cond(V("s"), "igual", "ok")], "combinar": "e", "manter_descartados": False}
    _, (passou,) = rodar_no("filtrar", cfg, ent, 1)
    assert [j["i"] for j in passou] == [1, 3]


def test_filtrar_manter_descartados_vira_saida_1(rodar_no):
    """NOV-02: com manter_descartados, o que não atende sai pela saída 1."""
    ent = [{"s": "ok", "i": 1}, {"s": "no", "i": 2}, {"s": "ok", "i": 3}]
    cfg = {"condicoes": [cond(V("s"), "igual", "ok")], "combinar": "e", "manter_descartados": True}
    _, (passou, descartado) = rodar_no("filtrar", cfg, ent, 2)
    assert [j["i"] for j in passou] == [1, 3] and [j["i"] for j in descartado] == [2]


def _regra(valor, rotulo):
    return {"condicoes": [cond("{{ $json.v }}", "igual", valor, "numero")], "combinar": "e", "rotulo": rotulo}


def test_escolher_roteia_pela_primeira_regra_e_outros(rodar_no):
    """NOV-02/B8: regras 0..n-1, 'outros' é a saída n; o item vai só para a primeira regra que casar."""
    cfg = {"regras": [_regra("1", "um"), _regra("2", "dois")], "saida_outros": True}
    ent = [{"v": 1}, {"v": 2}, {"v": 3}, {"v": 1}]
    _, (a, b, outros) = rodar_no("escolher", cfg, ent, 3)
    assert a == [{"v": 1}, {"v": 1}] and b == [{"v": 2}] and outros == [{"v": 3}]


def test_escolher_primeira_regra_vence_quando_ha_sobreposicao(rodar_no):
    """NOV-02/B8: item que casa duas regras vai só à primeira."""
    cfg = {"regras": [_regra("1", "a"), _regra("1", "b")], "saida_outros": False}
    _, (a, b) = rodar_no("escolher", cfg, [{"v": 1}], 2)
    assert a == [{"v": 1}] and b == []


def test_escolher_sem_outros_descarta(rodar_no):
    """NOV-02/B8: sem saida_outros, item sem regra é descartado."""
    cfg = {"regras": [_regra("1", "um")], "saida_outros": False}
    e, (a,) = rodar_no("escolher", cfg, [{"v": 1}, {"v": 9}], 1)
    assert e.status == "sucesso" and a == [{"v": 1}]


def test_escolher_aceita_10_regras_e_11_e_pendencia(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-02/B8: até 10 regras; 11 = pendência (200)."""
    f = fabrica_fluxo(grafo=h.cadeia2())

    def grafo(n):
        cfg = {"regras": [_regra(str(i), f"r{i}") for i in range(n)], "saida_outros": True}
        return h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("x", "escolher", cfg, x=1)], [("g", "x")])
    r = salvar_grafo(cliente_adm, f, grafo(10))
    assert r.status_code == 200 and r.json()["pendencias"] == []
    r = salvar_grafo(cliente_adm, f, grafo(11))
    assert r.status_code == 200 and r.json()["pendencias"]


def test_regex_acima_de_200_caracteres_e_pendencia(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-02/B8: regex de 200 chars passa; 201 = pendência ao salvar."""
    f = fabrica_fluxo(grafo=h.cadeia2())

    def grafo(n):
        cfg = {"condicoes": [cond(V(), "regex", "a" * n)], "combinar": "e"}
        return h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("x", "se", cfg, x=1)], [("g", "x")])
    assert salvar_grafo(cliente_adm, f, grafo(200)).json()["pendencias"] == []
    r = salvar_grafo(cliente_adm, f, grafo(201))
    assert r.status_code == 200 and r.json()["pendencias"]


def test_regex_catastrofico_estoura_50ms_vira_erro_expressao(rodar_no, no):
    """NOV-02/B8: ReDoS (a+)+$ sobre 'aaaa…b' não trava: termina rápido com erro 'expressao'."""
    inicio = time.monotonic()
    e, _ = rodar_no("se", {"condicoes": [cond(V(), "regex", "^(a+)+$")], "combinar": "e"}, [{"v": "a" * 40 + "b"}], 2)
    assert time.monotonic() - inicio < 5
    assert e.status == "erro" and no(e, "t").erro_categoria == "expressao"


def test_se_com_expressao_invalida_e_erro_expressao(rodar_no, no):
    """NOV-02/MV2-10: erro dentro da condição = erro do nó, categoria expressao."""
    e, _ = rodar_no("se", {"condicoes": [cond("{{ $json.nao.x }}", "igual", "1")], "combinar": "e"}, [{"v": 1}], 2)
    assert e.status == "erro" and no(e, "t").erro_categoria == "expressao"
