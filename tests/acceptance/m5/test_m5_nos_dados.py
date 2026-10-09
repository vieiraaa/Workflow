"""Aceite M5 parte B: nós de dados (NOV-03). Chaves e nomes de saída: MV2-15 B1, B2, B3, B9."""

import re

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]


# ---------------- Editar campos ----------------

def test_editar_campos_manual_com_caminho_e_sem_outros(rodar_no):
    """NOV-03: nome aceita caminho a.b (cria objeto aninhado); incluir_outros=false descarta o resto."""
    cfg = {"modo": "manual", "incluir_outros": False,
           "campos": [{"nome": "a.b", "valor": "{{ $json.n + 1 }}", "tipo": "numero"},
                      {"nome": "nome", "valor": "Sr. {{ $json.nome }}", "tipo": "texto"}]}
    _, (s,) = rodar_no("editar_campos", cfg, [{"n": 1, "nome": "Ana", "extra": True}])
    assert s == [{"a": {"b": 2}, "nome": "Sr. Ana"}]


def test_editar_campos_incluir_outros_preserva_e_sobrescreve(rodar_no):
    """NOV-03: incluir_outros=true mantém os campos de entrada; o campo editado sobrescreve."""
    cfg = {"modo": "manual", "incluir_outros": True, "campos": [{"nome": "n", "valor": "{{ $json.n * 10 }}", "tipo": "numero"}]}
    _, (s,) = rodar_no("editar_campos", cfg, [{"n": 1, "k": "v"}])
    assert s == [{"n": 10, "k": "v"}]


@pytest.mark.parametrize("valor,tipo,esperado", [("{{ $json.lista }}", "lista", [1, 2]), ("{{ $json.obj }}", "objeto", {"x": 1}),
                                                 ("{{ $json.n > 0 }}", "booleano", True), ("{{ $json.n }}", "numero", 3)])
def test_editar_campos_tipos(valor, tipo, esperado, rodar_no):
    """NOV-03/L12: tipos texto|numero|booleano|lista|objeto preservam o valor tipado."""
    cfg = {"modo": "manual", "incluir_outros": False, "campos": [{"nome": "r", "valor": valor, "tipo": tipo}]}
    _, (s,) = rodar_no("editar_campos", cfg, [{"n": 3, "lista": [1, 2], "obj": {"x": 1}}])
    assert s == [{"r": esperado}]


def test_editar_campos_modo_json(rodar_no):
    """NOV-03/B2: modo json — a chave 'json' com um objeto vira o json do item."""
    cfg = {"modo": "json", "json": "{{ $json.obj }}", "incluir_outros": False}
    _, (s,) = rodar_no("editar_campos", cfg, [{"obj": {"k": 1}, "x": 2}])
    assert s == [{"k": 1}]
    cfg = {"modo": "json", "json": '{"dobro": {{ $json.n * 2 }}, "nome": "{{ $json.nome }}"}', "incluir_outros": True}
    _, (s,) = rodar_no("editar_campos", cfg, [{"n": 4, "nome": "Ana"}])
    assert s == [{"n": 4, "nome": "Ana", "dobro": 8}]


# ---------------- Ordenar / Limitar / Remover duplicados ----------------

def test_ordenar_numerico_e_texto(rodar_no):
    """NOV-03: Ordenar asc/desc; números ordenam como números (10 > 9)."""
    ent = [{"n": 9, "t": "b"}, {"n": 10, "t": "a"}, {"n": 2, "t": "c"}]
    _, (s,) = rodar_no("ordenar", {"campos": [{"campo": "n", "ordem": "asc"}]}, ent)
    assert [j["n"] for j in s] == [2, 9, 10]
    _, (s,) = rodar_no("ordenar", {"campos": [{"campo": "n", "ordem": "desc"}]}, ent)
    assert [j["n"] for j in s] == [10, 9, 2]
    _, (s,) = rodar_no("ordenar", {"campos": [{"campo": "t", "ordem": "asc"}]}, ent)
    assert [j["t"] for j in s] == ["a", "b", "c"]


def test_ordenar_por_varios_campos_com_desempate(rodar_no):
    """NOV-03: vários campos desempatam na ordem dada."""
    ent = [{"g": "b", "n": 1}, {"g": "a", "n": 1}, {"g": "a", "n": 2}, {"g": "b", "n": 0}]
    _, (s,) = rodar_no("ordenar", {"campos": [{"campo": "g", "ordem": "asc"}, {"campo": "n", "ordem": "desc"}]}, ent)
    assert [(j["g"], j["n"]) for j in s] == [("a", 2), ("a", 1), ("b", 1), ("b", 0)]


def test_limitar_do_inicio_do_fim_e_acima_do_total(rodar_no):
    """NOV-03: Limitar {quantidade, de: inicio|fim}; quantidade maior que o total devolve todos."""
    ent = [{"i": i} for i in range(5)]
    _, (s,) = rodar_no("limitar", {"quantidade": 2, "de": "inicio"}, ent)
    assert [j["i"] for j in s] == [0, 1]
    _, (s,) = rodar_no("limitar", {"quantidade": 2, "de": "fim"}, ent)
    assert [j["i"] for j in s] == [3, 4]
    _, (s,) = rodar_no("limitar", {"quantidade": 50, "de": "inicio"}, ent)
    assert len(s) == 5


def test_remover_duplicados_todos_e_por_campos(rodar_no):
    """NOV-03: comparar todos (item inteiro) ou campos (mantém o primeiro)."""
    ent = [{"id": 1, "v": "a"}, {"id": 1, "v": "b"}, {"id": 1, "v": "a"}, {"id": 2, "v": "a"}]
    _, (s,) = rodar_no("remover_duplicados", {"comparar": "todos", "campos": []}, ent)
    assert s == [{"id": 1, "v": "a"}, {"id": 1, "v": "b"}, {"id": 2, "v": "a"}]
    _, (s,) = rodar_no("remover_duplicados", {"comparar": "campos", "campos": ["id"]}, ent)
    assert s == [{"id": 1, "v": "a"}, {"id": 2, "v": "a"}]


# ---------------- Separar lista / Agregar / Resumir ----------------

def test_separar_lista_de_objetos_com_e_sem_campos_do_pai(rodar_no):
    """NOV-03/B9: elemento objeto → json do item; incluir campos_pai mescla {**pai sem a lista, **elemento}."""
    ent = [{"id": 1, "itens": [{"a": 1}, {"a": 2}]}, {"id": 2, "itens": [{"a": 3}]}]
    _, (s,) = rodar_no("separar_lista", {"campo": "itens", "incluir": "nada"}, ent)
    assert s == [{"a": 1}, {"a": 2}, {"a": 3}]
    _, (s,) = rodar_no("separar_lista", {"campo": "itens", "incluir": "campos_pai"}, ent)
    assert s == [{"id": 1, "a": 1}, {"id": 1, "a": 2}, {"id": 2, "a": 3}]


def test_separar_lista_com_caminho_elemento_simples_e_vazia(rodar_no):
    """NOV-03/B9: caminho a.b; elemento não objeto vira {campo: elemento}; lista vazia = 0 itens."""
    _, (s,) = rodar_no("separar_lista", {"campo": "d.nums", "incluir": "nada"}, [{"d": {"nums": [7, 8]}}])
    assert s == [{"d.nums": 7}, {"d.nums": 8}] or s == [{"nums": 7}, {"nums": 8}]
    e, (s,) = rodar_no("separar_lista", {"campo": "itens", "incluir": "nada"}, [{"itens": []}])
    assert e.status == "sucesso" and s == []


def test_separar_lista_campo_inexistente_ou_nao_lista_e_erro(rodar_no, no):
    """NOV-03/B9: campo ausente ou que não é lista = erro do nó categoria 'expressao'."""
    for ent in ([{"x": 1}], [{"itens": "texto"}]):
        e, _ = rodar_no("separar_lista", {"campo": "itens", "incluir": "nada"}, ent)
        assert e.status == "erro" and no(e, "t").erro_categoria == "expressao"


def test_separar_lista_de_10001_elementos_estoura_limite_de_itens(rodar_no, no):
    """MV2-01+NOV-03: Separar lista gerando 10.001 itens → erro limite_itens."""
    e, _ = rodar_no("separar_lista", {"campo": "l", "incluir": "nada"}, [{"l": [{"i": i} for i in range(10001)]}])
    assert e.status == "erro" and no(e, "t").erro_categoria == "limite_itens"


def test_agregar_todos_e_campos(rodar_no):
    """NOV-03/B9: modo todos → 1 item {saida: [json…]}; modo campos (1 campo) → {saida: [valores]}; vários → um por campo."""
    ent = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    _, (s,) = rodar_no("agregar", {"modo": "todos", "campos": [], "saida": "todos"}, ent)
    assert s == [{"todos": ent}]
    _, (s,) = rodar_no("agregar", {"modo": "campos", "campos": ["a"], "saida": "lista"}, ent)
    assert s == [{"lista": [1, 2]}]
    _, (s,) = rodar_no("agregar", {"modo": "campos", "campos": ["a", "b"], "saida": "ignorada"}, ent)
    assert s == [{"a": [1, 2], "b": ["x", "y"]}]


def test_resumir_agrupado_todas_as_operacoes(rodar_no):
    """NOV-03/B1: 1 item por grupo (ordem da 1ª aparição) com agrupar_por + '<op>_<campo>'."""
    ent = [{"s": "a", "v": 1}, {"s": "b", "v": 10}, {"s": "a", "v": 3}, {"s": "a", "v": 3}]
    ops = [{"campo": "v", "op": o} for o in ("contar", "contar_unicos", "somar", "media", "min", "max", "concatenar")]
    _, (s,) = rodar_no("resumir", {"agrupar_por": ["s"], "operacoes": ops}, ent)
    assert [j["s"] for j in s] == ["a", "b"]
    a, b = s
    assert (a["contar_v"], a["contar_unicos_v"], a["somar_v"], a["min_v"], a["max_v"]) == (3, 2, 7, 1, 3)
    assert abs(a["media_v"] - 7 / 3) < 1e-9 and a["concatenar_v"] == "1, 3, 3"
    assert (b["contar_v"], b["somar_v"], b["media_v"], b["concatenar_v"]) == (1, 10, 10, "10")


def test_resumir_sem_agrupar_gera_um_item(rodar_no):
    """NOV-03/B1: sem agrupar_por = 1 item."""
    ent = [{"v": 1}, {"v": 2}, {"v": 6}]
    _, (s,) = rodar_no("resumir", {"agrupar_por": [], "operacoes": [{"campo": "v", "op": "somar"}, {"campo": "v", "op": "media"}]}, ent)
    assert s == [{"somar_v": 9, "media_v": 3}]


# ---------------- Data e hora ----------------

D = "2026-10-09T15:30:00.000-03:00"


def _dh(rodar_no, entrada, **cfg):
    base = {"operacao": "formatar", "campo": "d", "formato": "", "quantidade": 0, "unidade": "dias", "saida": "r"}
    base.update(cfg)
    e, (s,) = rodar_no("data_hora", base, [entrada])
    assert e.status == "sucesso", e.erro_resumo
    return s[0]


def test_data_hora_formatar(rodar_no):
    """NOV-03/B3: formatar com tokens Luxon; entrada sem offset = São Paulo; 'saida' é o campo gravado."""
    assert _dh(rodar_no, {"d": D}, operacao="formatar", formato="dd/MM/yyyy HH:mm")["r"] == "09/10/2026 15:30"
    assert _dh(rodar_no, {"d": "2026-10-09T15:30:00"}, operacao="formatar", formato="yyyy-MM-dd HH:mm:ss")["r"] == "2026-10-09 15:30:00"


@pytest.mark.parametrize("op,qtd,un,esperado", [
    ("somar", 2, "dias", "2026-10-11T15:30:00.000-03:00"), ("subtrair", 3, "horas", "2026-10-09T12:30:00.000-03:00"),
    ("somar", 45, "minutos", "2026-10-09T16:15:00.000-03:00"), ("somar", 1, "semanas", "2026-10-16T15:30:00.000-03:00"),
    ("somar", 1, "meses", "2026-11-09T15:30:00.000-03:00"), ("subtrair", 1, "dias", "2026-10-08T15:30:00.000-03:00"),
])
def test_data_hora_somar_subtrair(op, qtd, un, esperado, rodar_no):
    """NOV-03/B3: somar/subtrair devolvem toISO() Luxon com -03:00."""
    assert _dh(rodar_no, {"d": D}, operacao=op, quantidade=qtd, unidade=un)["r"] == esperado


@pytest.mark.parametrize("un,esperado", [
    ("dia", "2026-10-09T00:00:00.000-03:00"), ("mes", "2026-10-01T00:00:00.000-03:00"),
    ("hora", "2026-10-09T15:00:00.000-03:00"), ("semana", "2026-10-05T00:00:00.000-03:00")])
def test_data_hora_inicio_de(un, esperado, rodar_no):
    """NOV-03/B3: inicio_de dia|semana(segunda)|mes|hora."""
    assert _dh(rodar_no, {"d": D}, operacao="inicio_de", unidade=un)["r"] == esperado


def test_data_hora_diferenca_em_unidade(rodar_no):
    """NOV-03/B3: diferença entre campo e campo2, número na unidade (módulo; o sinal não é especificado)."""
    ent = {"d": "2026-10-09T12:00:00-03:00", "d2": "2026-10-07T12:00:00-03:00"}
    assert abs(_dh(rodar_no, ent, operacao="diferenca", campo2="d2", unidade="dias")["r"]) == 2
    assert abs(_dh(rodar_no, ent, operacao="diferenca", campo2="d2", unidade="horas")["r"]) == 48


def test_data_hora_agora_e_saida_vazia_sobrescreve(rodar_no):
    """NOV-03/B3: agora devolve toISO() Luxon; saida vazia sobrescreve 'campo'."""
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-03:00$", _dh(rodar_no, {"x": 1}, operacao="agora")["r"])
    s = _dh(rodar_no, {"d": D}, operacao="somar", quantidade=1, unidade="dias", saida="")
    assert s["d"] == "2026-10-10T15:30:00.000-03:00"


def test_data_hora_valor_invalido_e_erro_do_no(rodar_no, no):
    """NOV-03: data ilegível → erro do nó (nunca 500)."""
    e, _ = rodar_no("data_hora", {"operacao": "formatar", "campo": "d", "formato": "yyyy", "saida": "r"}, [{"d": "nao e data"}])
    assert e.status == "erro" and no(e, "t").erro_categoria
