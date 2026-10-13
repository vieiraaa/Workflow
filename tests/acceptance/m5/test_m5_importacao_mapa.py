"""Aceite M5 parte C (aprofundamento): mapa de parâmetros n8n → nativo (IMP-03, MV2-20) e exportação n8n (IMP-05)."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

P = "n8n-nodes-base."


def no_n8n(nome, tipo, params=None, pos=(0, 0), versao=1, **extra):
    return {"id": f"id-{nome}", "name": nome, "type": P + tipo, "typeVersion": versao, "position": list(pos), "parameters": params or {}, **extra}


def liga(origem, *saidas):
    return {origem: {"main": [[{"node": d, "type": "main", "index": 0} for d in saida] for saida in saidas]}}


def fluxo_n8n(nos, *conexoes):
    c = {}
    for x in conexoes:
        c.update(x)
    return {"name": "Mapa fictício", "nodes": nos, "connections": c, "pinData": {}, "active": False, "settings": {}}


@pytest.fixture
def importado(cliente_adm, modelos):
    def _i(obj):
        antes = set(modelos.Fluxo.objects.values_list("pk", flat=True))
        arq = SimpleUploadedFile("f.json", json.dumps(obj).encode(), content_type="application/json")
        r = cliente_adm.post(reverse("fluxos:importar"), {"arquivo": arq})
        novos = modelos.Fluxo.objects.exclude(pk__in=antes)
        assert novos.count() == 1, (r.status_code, r.content[:300])
        return novos.get()

    return _i


@pytest.fixture
def um_no(importado):
    """um_no(tipo, params, versao) → (Fluxo, config do nó 'Alvo', nó 'Alvo')."""

    def _u(tipo, params, versao=1, **extra):
        f = importado(fluxo_n8n([no_n8n("Início", "manualTrigger"), no_n8n("Alvo", tipo, params, versao=versao, pos=(1, 0), **extra)], liga("Início", ["Alvo"])))
        n = next(x for x in f.grafo["nos"] if x["titulo"] == "Alvo")
        return f, n["config"], n

    return _u


def _cond(esq, op, tipo, dir_=None):
    c = {"leftValue": esq, "operator": {"type": tipo, "operation": op}}
    if dir_ is not None:
        c["rightValue"] = dir_
    return c


# ---------------- set ----------------

def test_set_v3_assignments_e_tipos(um_no):
    """MV2-20: set v3 → editar_campos; tipos string/number/boolean/array/object; includeOtherFields."""
    params = {"mode": "manual", "includeOtherFields": True, "assignments": {"assignments": [
        {"id": "1", "name": "a", "value": "={{ $json.x }}", "type": "string"}, {"id": "2", "name": "b.c", "value": 2, "type": "number"},
        {"id": "3", "name": "d", "value": True, "type": "boolean"}, {"id": "4", "name": "e", "value": "={{ [1] }}", "type": "array"},
        {"id": "5", "name": "f", "value": "={{ {} }}", "type": "object"}]}}
    _, c, n = um_no("set", params, 3)
    assert n["tipo"] == "editar_campos" and c["modo"] == "manual" and c["incluir_outros"] is True
    assert [(x["nome"], x["tipo"]) for x in c["campos"]] == [("a", "texto"), ("b.c", "numero"), ("d", "booleano"), ("e", "lista"), ("f", "objeto")]
    assert c["campos"][0]["valor"] == "={{ $json.x }}"


def test_set_v3_raw_json(um_no):
    """MV2-20: mode raw + jsonOutput → modo json + json."""
    _, c, _ = um_no("set", {"mode": "raw", "jsonOutput": '={{ {"a": 1} }}', "includeOtherFields": False}, 3)
    assert c["modo"] == "json" and "a" in c["json"] and c["incluir_outros"] is False


# ---------------- if / filter / switch ----------------

OPERACOES = [("equals", "igual"), ("notEquals", "diferente"), ("gt", "maior"), ("gte", "maior_igual"), ("lt", "menor"), ("lte", "menor_igual"),
             ("contains", "contem"), ("notContains", "nao_contem"), ("startsWith", "comeca_com"), ("endsWith", "termina_com"),
             ("empty", "vazio"), ("notEmpty", "nao_vazio"), ("regex", "regex"), ("exists", "existe"), ("notExists", "nao_existe")]
TIPOS_COND = [("string", "texto"), ("number", "numero"), ("dateTime", "data"), ("boolean", "booleano"), ("array", "lista"), ("object", "objeto")]


@pytest.mark.parametrize("tipo_n8n,tipo", [("if", "se"), ("filter", "filtrar")])
def test_if_e_filter_operadores_tipos_e_combinador(tipo_n8n, tipo, um_no):
    """MV2-20: conditions → condicoes (esquerda/direita/operador/tipo) + combinar (and→e, or→ou)."""
    conds = [_cond("={{ $json.a }}", op, "string", "x") for op, _ in OPERACOES] + [_cond("={{ $json.b }}", "equals", t, "1") for t, _ in TIPOS_COND]
    _, c, n = um_no(tipo_n8n, {"conditions": {"conditions": conds, "combinator": "or"}}, 2)
    assert n["tipo"] == tipo and c["combinar"] == "ou"
    ops = [x["operador"] for x in c["condicoes"][: len(OPERACOES)]]
    assert ops == [o for _, o in OPERACOES]
    assert [x["tipo"] for x in c["condicoes"][len(OPERACOES):]] == [t for _, t in TIPOS_COND]
    assert c["condicoes"][0]["esquerda"] == "={{ $json.a }}" and c["condicoes"][0]["direita"] == "x"


def test_if_combinator_and(um_no):
    """MV2-20: combinator and → 'e'."""
    _, c, _ = um_no("if", {"conditions": {"conditions": [_cond("={{ $json.a }}", "equals", "number", 1)], "combinator": "and"}}, 2)
    assert c["combinar"] == "e" and c["condicoes"][0]["tipo"] == "numero"


def test_switch_v3_regras_rotulos_e_outros(um_no):
    """MV2-20: rules.values → regras[{condicoes, combinar, rotulo}]; fallbackOutput extra → saida_outros."""
    regras = [{"conditions": {"conditions": [_cond("={{ $json.v }}", "equals", "number", i)], "combinator": "and"}, "outputKey": f"Saída {i}"} for i in (1, 2)]
    _, c, n = um_no("switch", {"rules": {"values": regras}, "options": {"fallbackOutput": "extra"}}, 3)
    assert n["tipo"] == "escolher" and c["saida_outros"] is True
    assert [r["rotulo"] for r in c["regras"]] == ["Saída 1", "Saída 2"] and c["regras"][1]["condicoes"][0]["direita"] in (2, "2")
    _, c2, _ = um_no("switch", {"rules": {"values": regras}}, 3)
    assert c2["saida_outros"] is False


# ---------------- merge / sort / limit / removeDuplicates ----------------

@pytest.mark.parametrize("params,esperado", [
    ({"mode": "append"}, {"modo": "anexar"}),
    ({"mode": "combine", "combineBy": "combineByPosition"}, {"modo": "combinar_por_posicao"}),
    ({"mode": "chooseBranch"}, {"modo": "escolher_entrada"}),
    ({"mode": "combine", "combineBy": "combineByFields", "fieldsToMatchString": "id", "joinMode": "keepMatches"}, {"modo": "combinar_por_campo", "campo1": "id", "campo2": "id", "tipo": "dentro"}),
    ({"mode": "combine", "combineBy": "combineByFields", "fieldsToMatchString": "id", "joinMode": "keepEverything"}, {"modo": "combinar_por_campo", "tipo": "externa"}),
    ({"mode": "combine", "combineBy": "combineByFields", "fieldsToMatchString": "id", "joinMode": "enrichInput1"}, {"modo": "combinar_por_campo", "tipo": "esquerda"}),
    ({"mode": "combine", "combineBy": "combineByFields", "fields": {"values": [{"field1": "a", "field2": "b"}]}, "joinMode": "enrichInput2"},
     {"modo": "combinar_por_campo", "campo1": "a", "campo2": "b", "tipo": "direita"}),
])
def test_merge_v3(params, esperado, um_no):
    """MV2-20: merge v3 → juntar (modos, campos do primeiro par, joinMode)."""
    _, c, n = um_no("merge", params, 3)
    assert n["tipo"] == "juntar" and esperado.items() <= c.items() and 2 <= c["entradas"] <= 4


def test_sort_limit_remove_duplicates(um_no):
    """MV2-20: sort/limit/removeDuplicates."""
    _, c, _ = um_no("sort", {"sortFieldsUi": {"sortField": [{"fieldName": "n", "order": "descending"}, {"fieldName": "t"}]}})
    assert c["campos"][0] == {"campo": "n", "ordem": "desc"} and c["campos"][1] == {"campo": "t", "ordem": "asc"}
    _, c, _ = um_no("limit", {"maxItems": 3, "keep": "lastItems"})
    assert (c["quantidade"], c["de"]) == (3, "fim")
    _, c, _ = um_no("limit", {"maxItems": 7})
    assert (c["quantidade"], c["de"]) == (7, "inicio")
    _, c, _ = um_no("removeDuplicates", {"compare": "allFields"}, 2)
    assert c["comparar"] == "todos"
    _, c, _ = um_no("removeDuplicates", {"compare": "selectedFields", "fieldsToCompare": "a,b"}, 2)
    assert c["comparar"] == "campos" and c["campos"] == ["a", "b"]


# ---------------- splitOut / aggregate / summarize / dateTime ----------------

def test_split_out_e_aggregate(um_no):
    """MV2-20: splitOut (campo, incluir) e aggregate (campos | todos + saida)."""
    _, c, _ = um_no("splitOut", {"fieldToSplitOut": "itens", "include": "allOtherFields"}, 1)
    assert c["campo"] == "itens" and c["incluir"] == "campos_pai"
    _, c, _ = um_no("splitOut", {"fieldToSplitOut": "itens", "include": "noOtherFields"}, 1)
    assert c["incluir"] == "nada"
    _, c, _ = um_no("aggregate", {"aggregate": "aggregateIndividualFields", "fieldsToAggregate": {"fieldToAggregate": [{"fieldToAggregate": "a"}, {"fieldToAggregate": "b"}]}}, 1)
    assert c["modo"] == "campos" and c["campos"] == ["a", "b"]
    _, c, _ = um_no("aggregate", {"aggregate": "aggregateAllItemData", "destinationFieldName": "todos"}, 1)
    assert c["modo"] == "todos" and c["saida"] == "todos"


def test_summarize(um_no):
    """MV2-20: summarize → agrupar_por e operações (count, countUnique, sum, average, min, max, concatenate)."""
    mapa = [("count", "contar"), ("countUnique", "contar_unicos"), ("sum", "somar"), ("average", "media"), ("min", "min"), ("max", "max"), ("concatenate", "concatenar")]
    params = {"fieldsToSplitBy": "g,h", "fieldsToSummarize": {"values": [{"aggregation": a, "field": "v"} for a, _ in mapa]}}
    _, c, n = um_no("summarize", params, 1)
    assert n["tipo"] == "resumir" and c["agrupar_por"] == ["g", "h"]
    assert [(o["op"], o["campo"]) for o in c["operacoes"]] == [(o, "v") for _, o in mapa]


@pytest.mark.parametrize("op_n8n,op", [("getCurrentDate", "agora"), ("addToDate", "somar"), ("subtractFromDate", "subtrair"), ("formatDate", "formatar"),
                                       ("getTimeBetweenDates", "diferenca"), ("roundDate", "inicio_de")])
def test_date_time_operacoes(op_n8n, op, um_no):
    """MV2-20: dateTime v2 → data_hora.operacao."""
    _, c, n = um_no("dateTime", {"action": op_n8n, "operation": op_n8n}, 2)
    assert n["tipo"] == "data_hora" and c["operacao"] == op


# ---------------- splitInBatches / stop / code / sticky ----------------

def _lotes(importado):
    nos = [no_n8n("Início", "manualTrigger"), no_n8n("Lotes", "splitInBatches", {"batchSize": 5}, versao=3, pos=(1, 0)),
           no_n8n("Fim", "noOp", pos=(2, 0)), no_n8n("Corpo", "noOp", pos=(2, 100))]
    # n8n: saída 0 = done (→ Fim), saída 1 = loop (→ Corpo); Corpo volta para Lotes
    f = importado(fluxo_n8n(nos, liga("Início", ["Lotes"]), liga("Lotes", ["Fim"], ["Corpo"]), liga("Corpo", ["Lotes"])))
    g = f.grafo
    por_id = {n["id"]: n["titulo"] for n in g["nos"]}
    return f, sorted((por_id[a["de"]], a["saida"], por_id[a["para"]], a["entrada"]) for a in g["arestas"])


def test_split_in_batches_troca_as_saidas_done_e_loop(importado):
    """MV2-20: n8n done(0)/loop(1) ↔ nossa pronto(1)/loop(0): as arestas de saída são trocadas na importação."""
    f, ars = _lotes(importado)
    assert next(n for n in f.grafo["nos"] if n["titulo"] == "Lotes")["config"]["tamanho_lote"] == 5
    assert ars == sorted([("Início", 0, "Lotes", 0), ("Lotes", 1, "Fim", 0), ("Lotes", 0, "Corpo", 0), ("Corpo", 0, "Lotes", 0)])


def test_laco_importado_nao_gera_pendencia_de_ciclo(importado, cliente_adm, salvar_grafo):
    """MV2-20+NOV-04: o laço do Repetir em lotes importado é aceito (sem pendência de ciclo)."""
    f, _ = _lotes(importado)
    r = salvar_grafo(cliente_adm, f, f.grafo)
    assert r.status_code == 200 and not any("ciclo" in p["mensagem"] for p in r.json()["pendencias"])


def test_export_n8n_troca_de_volta_as_saidas_do_lote_e_saida_vira_noop(cliente_adm, importado):
    """MV2-20: exportar para n8n devolve done(0)/loop(1) e o nó 'saida' vira noOp com o mesmo nome."""
    f, _ = _lotes(importado)
    g = json.loads(json.dumps(f.grafo))
    por = {n["titulo"]: n["id"] for n in g["nos"]}
    g["nos"].append({"id": "fim_saida", "tipo": "saida", "titulo": "Resultado", "posicao": {"x": 9, "y": 9}, "config": {},
                     "desativado": False, "executar_uma_vez": False, "em_erro": "parar"})
    g["arestas"].append({"de": por["Fim"], "saida": 0, "para": "fim_saida", "entrada": 0})
    f.grafo = g
    f.save()
    d = json.loads(cliente_adm.get(reverse("fluxos:exportar_n8n", kwargs={"pk": f.pk})).content)
    assert [x["node"] for x in d["connections"]["Lotes"]["main"][0]] == ["Fim"]
    assert [x["node"] for x in d["connections"]["Lotes"]["main"][1]] == ["Corpo"]
    assert next(n for n in d["nodes"] if n["name"] == "Resultado")["type"] == P + "noOp"
    assert next(n for n in d["nodes"] if n["name"] == "Lotes")["type"] == P + "splitInBatches"


def test_stop_and_error_e_code_modos(um_no):
    """MV2-20: stopAndError.errorMessage → mensagem; code runOnceForAllItems/EachItem → modos; jsCode → codigo."""
    _, c, n = um_no("stopAndError", {"errorMessage": "={{ 'Falhou ' + $json.id }}"}, 1)
    assert n["tipo"] == "parar_com_erro" and c["mensagem"] == "={{ 'Falhou ' + $json.id }}"
    _, c, _ = um_no("code", {"jsCode": "return [];"}, 2)
    assert c["modo"] == "uma_vez_para_todos" and c["codigo"] == "return [];"
    _, c, _ = um_no("code", {"mode": "runOnceForAllItems", "jsCode": "return [];"}, 2)
    assert c["modo"] == "uma_vez_para_todos"
    _, c, n = um_no("code", {"mode": "runOnceForEachItem", "jsCode": "return {json: {}};"}, 2)
    assert c["modo"] == "uma_vez_por_item" and n["desativado"] is True


@pytest.mark.parametrize("cor,esperada", [(1, "amarela"), (None, "amarela"), (2, "cinza"), (3, "cinza"), (4, "verde"), (5, "azul"), (6, "azul"), (7, "cinza")])
def test_sticky_note_cores_tamanho_e_texto(cor, esperada, importado):
    """MV2-20: stickyNote → nota (content→texto, width/height→tamanho, color 1..7 → nome)."""
    params = {"content": "## Título\nCorpo da nota", "width": 320, "height": 180}
    if cor is not None:
        params["color"] = cor
    f = importado(fluxo_n8n([no_n8n("Início", "manualTrigger"), no_n8n("Nota", "stickyNote", params, versao=1, pos=(40, 60))]))
    (nota,) = f.grafo["notas"]
    assert nota["cor"] == esperada and nota["texto"] == "## Título\nCorpo da nota" and nota["tamanho"] == {"l": 320, "a": 180}
    assert nota["posicao"] == {"x": 40, "y": 60}


def test_parametro_desconhecido_vira_ajuste_nunca_erro(importado):
    """MV2-20: parâmetro que o mapa não conhece → 'ajustes' no relatório, importação segue."""
    f = importado(fluxo_n8n([no_n8n("Início", "manualTrigger"), no_n8n("Alvo", "noOp", {"parametroInventado": 1}, pos=(1, 0))], liga("Início", ["Alvo"])))
    assert any(a["no"] == "Alvo" for a in f.relatorio_importacao["ajustes"])
    assert next(n for n in f.grafo["nos"] if n["titulo"] == "Alvo")["tipo"] == "sem_operacao"
