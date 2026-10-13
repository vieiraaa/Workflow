"""Adversarial M5: nó Código — permissões (codigo.editar: só Adm) por TODOS os caminhos e vazamento entre execuções.
O isolamento do runtime em si (fugas do vm, rede, fs) é do Revisor de Segurança (test_revisao_seguranca.py)."""

import copy
import json
import time

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

MSG = "Só o administrador pode criar ou editar o nó Código."


def cod(codigo, modo="uma_vez_para_todos"):
    return {"modo": modo, "codigo": codigo}


@pytest.fixture
def fluxo_com_codigo(fabrica_fluxo, h):
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("cod", "codigo", cod("return $input.all();"), x=2, titulo="Meu código"),
                  dados_fixos={"d": h.itens({"v": "A"})})
    return fabrica_fluxo(grafo=g, status="rascunho")


def _salvar(cliente, f, g, salvar_grafo):
    return salvar_grafo(cliente, f, g)


def _intacto(f, antes):
    f.refresh_from_db()
    assert f.grafo == antes


# ---------------- Coordenador tentando criar/alterar Código ----------------

def test_coordenador_adiciona_no_codigo_e_403_com_mensagem_exata(cliente_coordenador, fabrica_fluxo, salvar_grafo, h):
    """MV2-18 C5c: Coordenador ADICIONA nó Código ao salvar → 403 JSON com a mensagem exata; nada gravado."""
    f = fabrica_fluxo(grafo=h.cadeia2(h.no2("a", "sem_operacao", x=1)), status="rascunho")
    antes = copy.deepcopy(f.grafo)
    g = copy.deepcopy(f.grafo)
    g["nos"].append(h.no2("novo", "codigo", cod("return [];"), x=9, titulo="Novo código"))
    g["arestas"].append(h.aresta("a", "novo"))
    r = salvar_grafo(cliente_coordenador, f, g)
    assert r.status_code == 403
    assert r.json() == {"ok": False, "erros": [{"campo": None, "mensagem": MSG}]}
    _intacto(f, antes)


@pytest.mark.parametrize("mut", [
    lambda n: n["config"].update(codigo="return [{json:{pwn:1}}];"),
    lambda n: n["config"].update(modo="uma_vez_por_item"),
    lambda n: n.update(desativado=True),
    lambda n: n["config"].update(codigo=n["config"]["codigo"] + " "),
    lambda n: n["config"].update(codigo=n["config"]["codigo"] + "//" + "x" * 10000),
], ids=["codigo", "modo", "desativar", "espaco_no_fim", "comentario_grande"])
def test_coordenador_altera_no_codigo_existente_e_403(mut, cliente_coordenador, fluxo_com_codigo, salvar_grafo):
    """MV2-18 C5c: alterar config (codigo/modo, até 1 espaço) ou `desativado` de nó Código existente → 403, nada gravado."""
    f = fluxo_com_codigo
    antes = copy.deepcopy(f.grafo)
    g = copy.deepcopy(f.grafo)
    mut(next(n for n in g["nos"] if n["id"] == "cod"))
    r = salvar_grafo(cliente_coordenador, f, g)
    assert r.status_code == 403 and r.json()["erros"][0]["mensagem"] == MSG
    _intacto(f, antes)


def test_coordenador_reativa_codigo_importado_desativado_e_403(cliente_coordenador, fabrica_fluxo, salvar_grafo, h):
    """MV2-18 C5c/IMP-04: nó Código desativado (como sai da importação) NÃO pode ser reativado por Coordenador."""
    g = h.cadeia2(h.no2("cod", "codigo", cod("return [];"), x=1, desativado=True))
    f = fabrica_fluxo(grafo=g, status="rascunho")
    antes = copy.deepcopy(f.grafo)
    g2 = copy.deepcopy(g)
    g2["nos"][1]["desativado"] = False
    r = salvar_grafo(cliente_coordenador, f, g2)
    assert r.status_code == 403
    _intacto(f, antes)


def test_coordenador_converte_outro_no_em_codigo_trocando_o_tipo(cliente_coordenador, fabrica_fluxo, salvar_grafo, h):
    """MV2-18 C5c: trocar o `tipo` de um nó existente para `codigo` (mesmo id/título) conta como criar Código → 403."""
    f = fabrica_fluxo(grafo=h.cadeia2(h.no2("a", "sem_operacao", x=1)), status="rascunho")
    antes = copy.deepcopy(f.grafo)
    g = copy.deepcopy(f.grafo)
    g["nos"][1].update(tipo="codigo", config=cod("return [];"))
    assert salvar_grafo(cliente_coordenador, f, g).status_code == 403
    _intacto(f, antes)


def test_coordenador_salva_sem_mexer_no_codigo_passa(cliente_coordenador, fluxo_com_codigo, salvar_grafo):
    """MV2-18 C5c: salvar sem mexer no Código passa (controle): outro nó pode mudar de título."""
    f = fluxo_com_codigo
    g = copy.deepcopy(f.grafo)
    next(n for n in g["nos"] if n["id"] == "d")["titulo"] = "Dados renomeados"
    r = salvar_grafo(cliente_coordenador, f, g)
    assert r.status_code == 200 and r.json()["ok"] is True
    f.refresh_from_db()
    assert next(n for n in f.grafo["nos"] if n["id"] == "cod")["config"]["codigo"] == "return $input.all();"


def test_coordenador_nao_burla_pela_versao_1(cliente_coordenador, fabrica_fluxo, salvar_grafo, grafo_valido_v1):
    """MV2-03/C5c: grafo VERSÃO 1 com nó `codigo` (a conversão v1→v2 não pode ser atalho): 400 (tipo desconhecido no v1) ou
    403; nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    grafo_valido_v1["nos"].append({"id": "c", "tipo": "codigo", "titulo": "C", "posicao": {"x": 1, "y": 1},
                                   "config": {"modo": "uma_vez_para_todos", "codigo": "return [];"}})
    r = salvar_grafo(cliente_coordenador, f, grafo_valido_v1)
    assert r.status_code in (400, 403)
    _intacto(f, antes)


@pytest.mark.parametrize("tipo", ["Codigo", "CODIGO", "codigo ", " codigo", "código", "code", "codigo\x00", "codigo​"])
def test_tipo_disfarcado_de_codigo_e_formato_invalido(tipo, cliente_coordenador, fabrica_fluxo, salvar_grafo, h):
    """MV2-02/C5c: variações de caixa/espaço/unicode do tipo `codigo` não passam como outro tipo: 400 de formato, nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    g = copy.deepcopy(f.grafo)
    g["nos"].append(h.no2("c", tipo, cod("return [];"), x=9, titulo="C"))
    r = salvar_grafo(cliente_coordenador, f, g)
    assert r.status_code in (400, 403)
    _intacto(f, antes)


def test_base_nao_salva_grafo_com_codigo(cliente_base, fluxo_com_codigo, salvar_grafo):
    """PRM-02/C5c: Base nunca salva grafo (403), com ou sem Código."""
    f = fluxo_com_codigo
    antes = copy.deepcopy(f.grafo)
    assert salvar_grafo(cliente_base, f, copy.deepcopy(f.grafo)).status_code == 403
    _intacto(f, antes)


def test_editar_fluxo_nao_aceita_grafo_no_formulario(cliente_coordenador, fluxo_com_codigo, h):
    """C5c: fluxos:editar (nome/descrição) ignora um campo `grafo` forjado: o Código não muda por esse caminho."""
    f = fluxo_com_codigo
    antes = copy.deepcopy(f.grafo)
    g = copy.deepcopy(f.grafo)
    next(n for n in g["nos"] if n["id"] == "cod")["config"]["codigo"] = "return [{json:{pwn:1}}];"
    cliente_coordenador.post(reverse("fluxos:editar", kwargs={"pk": f.pk}),
                             {"nome": f.nome, "descricao": "", "grafo": json.dumps(g)})
    _intacto(f, antes)


def test_executar_no_ignora_codigo_enviado_no_post(cliente_coordenador, fluxo_com_codigo, modelos, no):
    """C5c/MV2-06: executar_no só aceita `no_id`; um campo `codigo`/`config` forjado no POST não substitui o Código salvo."""
    f = fluxo_com_codigo
    r = cliente_coordenador.post(reverse("fluxos:executar_no", kwargs={"pk": f.pk}),
                                 {"no_id": "cod", "codigo": "return [{json:{pwn:1}}];",
                                  "config": json.dumps(cod("return [{json:{pwn:1}}];"))})
    assert r.status_code in (200, 302)
    e = modelos.Execucao.objects.get()
    n = no(e, "cod")
    assert [i["json"] for i in n.saida] == [{"v": "A"}]


def test_qualquer_papel_com_acesso_executa_fluxo_com_codigo(cliente_coordenador, cliente_base, cliente_adm, fabrica_fluxo, h, modelos):
    """MV2-18 C5c (controle): Coordenador (rascunho) e Base (ativo) EXECUTAM fluxo com Código; o Código roda."""
    g = h.cadeia2(h.no2("cod", "codigo", cod("return [{json:{ok: 1}}];"), x=1))
    fr = fabrica_fluxo(grafo=g, status="rascunho")
    fa = fabrica_fluxo(grafo=g, status="ativo")
    assert cliente_coordenador.post(reverse("fluxos:executar", kwargs={"pk": fr.pk})).status_code == 302
    assert cliente_base.post(reverse("fluxos:executar", kwargs={"pk": fa.pk})).status_code == 302
    assert modelos.Execucao.objects.filter(status="sucesso").count() == 2


# ---------------- Código via importação / colar ----------------

def test_importado_por_coordenador_nativo_chega_desativado_e_nao_executa(cliente_coordenador, cliente_adm, fluxo_com_codigo, imp, modelos, h, no):
    """SEG-19/IMP-04: nó Código importado (formato nativo, mesmo marcado desativado=false) entra DESATIVADO; executar não
    roda o código (o item passa sem alteração) e o Coordenador não consegue reativar."""
    g = copy.deepcopy(fluxo_com_codigo.grafo)
    next(n for n in g["nos"] if n["id"] == "cod")["config"]["codigo"] = "return [{json:{pwn:1}}];"
    next(n for n in g["nos"] if n["id"] == "cod")["desativado"] = False
    modelos.Fluxo.objects.filter(pk=fluxo_com_codigo.pk).update(grafo=g)
    conteudo = imp.exportar(cliente_adm, fluxo_com_codigo).content
    antes = imp.pks()
    r = imp.importar(cliente_coordenador, conteudo, json_=False)
    assert r.status_code in (200, 302)
    f = imp.novos(antes).get()
    n = next(n for n in f.grafo["nos"] if n["tipo"] == "codigo")
    assert n["desativado"] is True
    # executa: o Código desativado repassa os itens
    cliente_coordenador.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    e = modelos.Execucao.objects.filter(fluxo=f).get()
    assert [i["json"] for i in no(e, "cod").saida] == [{"v": "A"}] and no(e, "cod").status == "desativado"


def test_importado_n8n_code_node_chega_desativado_mesmo_com_disabled_false(cliente_coordenador, cliente_adm, imp):
    """SEG-19/IMP-04: n8n `code` com disabled:false (ou ausente) vira nó Código DESATIVADO + aviso no relatório."""
    obj = imp.n8n([imp.n8n_no("Início", "manualTrigger", pos=(0, 0)),
                   imp.n8n_no("Cod", "code", {"mode": "runOnceForAllItems", "jsCode": "return $input.all();"}, pos=(200, 0), disabled=False)],
                  [imp.liga("Início", ["Cod"])])
    for cli in (cliente_coordenador, cliente_adm):
        antes = imp.pks()
        r = imp.importar(cli, obj)
        assert r.status_code in (200, 302), r.content[:200]
        f = imp.novos(antes).get()
        cods = [n for n in f.grafo["nos"] if n["tipo"] == "codigo"]
        assert cods and all(n["desativado"] for n in cods)
        assert "Cod" in json.dumps(f.relatorio_importacao.get("codigo_desativado", []))


def test_colar_no_codigo_de_outro_fluxo_exige_adm(cliente_coordenador, fluxo_com_codigo, fabrica_fluxo, salvar_grafo):
    """EDV-03 / C5c: copiar/colar seleção entre fluxos é um save do grafo; Coordenador colando o nó Código copiado → 403."""
    destino = fabrica_fluxo(status="rascunho")
    antes = copy.deepcopy(destino.grafo)
    g = copy.deepcopy(destino.grafo)
    g["nos"].append(copy.deepcopy(next(n for n in fluxo_com_codigo.grafo["nos"] if n["tipo"] == "codigo")))
    g["nos"][-1].update(id="colado", titulo="Meu código (cópia)")
    assert salvar_grafo(cliente_coordenador, destino, g).status_code == 403
    _intacto(destino, antes)


# ---------------- vazamento entre execuções / usuários ----------------

def test_codigo_nao_ve_estado_nem_dados_de_outra_execucao(cliente_adm, cliente_coordenador, fabrica_fluxo, h, no, nos_de):
    """SEG-17: um processo por execução de nó. O Código do Adm grava em globalThis e loga; o Código do Coordenador
    (outro fluxo/usuário/execução) não enxerga o estado, os dados nem os logs do primeiro."""
    ga = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                   h.no2("cod", "codigo", cod("globalThis.__seg = 'ADM-SEGREDO'; console.log('log-do-adm'); return [{json:{ok: 1}}];"), x=2, titulo="Cod"),
                   dados_fixos={"d": h.itens({"v": "DADO-A-SECRETO"})})
    gb = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                   h.no2("cod", "codigo", cod("return [{json:{seg: typeof globalThis.__seg, g: String(globalThis.__seg), n: $('Dados').all().length, v: $('Dados').first().json.v}}];"), x=2, titulo="Cod"),
                   dados_fixos={"d": h.itens({"v": "DADO-B"})})
    fa, fb = fabrica_fluxo(grafo=ga, status="ativo"), fabrica_fluxo(grafo=gb, status="ativo")
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": fa.pk}))
    r = cliente_coordenador.post(reverse("fluxos:executar", kwargs={"pk": fb.pk}))
    assert r.status_code == 302
    from django.apps import apps
    eb = apps.get_model("execucoes", "Execucao").objects.get(fluxo=fb)
    assert eb.status == "sucesso"
    saida = no(eb, "cod").saida[0]["json"]
    assert saida == {"seg": "undefined", "g": "undefined", "n": 1, "v": "DADO-B"}
    tudo = json.dumps([[n.entrada, n.saida, n.logs, n.requisicoes, n.erro_mensagem] for n in nos_de(eb)])
    assert "DADO-A-SECRETO" not in tudo and "ADM-SEGREDO" not in tudo and "log-do-adm" not in tudo


def test_logs_de_uma_execucao_nao_aparecem_em_outra_e_sao_limitados(cliente_adm, fabrica_fluxo, h, no, modelos):
    """MV2-18 C5a: console.log gigante (100.000 linhas e uma linha de 3 MB) → no máximo 200 linhas gravadas; a execução seguinte
    começa com logs vazios."""
    g = h.cadeia2(h.no2("cod", "codigo", cod("for (let i = 0; i < 100000; i++) console.log('linha ' + i); console.log('x'.repeat(3000000)); return [{json:{}}];"), x=1, titulo="Cod"))
    f = fabrica_fluxo(grafo=g, status="ativo")
    t0 = time.time()
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    e = modelos.Execucao.objects.get(fluxo=f)
    assert e.status in ("sucesso", "erro") and time.time() - t0 < 60
    n = no(e, "cod")
    assert len(n.logs) <= 200
    g2 = h.cadeia2(h.no2("cod", "codigo", cod("return [{json:{}}];"), x=1, titulo="Cod"))
    f2 = fabrica_fluxo(grafo=g2, status="ativo")
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f2.pk}))
    assert no(modelos.Execucao.objects.get(fluxo=f2), "cod").logs == []


RETORNOS_HOSTIS = {
    "toJSON_lanca": "return [{json: {toJSON() { throw new Error('boom'); }}}];",
    "getter_lanca": "return [{json: {get x() { throw new Error('getter'); }}}];",
    "json_getter_lanca": "return [{get json() { throw new Error('g'); }}];",
    "circular": "const a = {}; a.a = a; return [{json: a}];",
    "bigint": "return [{json: {n: 10n}}];",
    "symbol": "return [{json: {s: Symbol('x')}}];",
    "funcao": "return [{json: {f: () => 1}}];",
    "proxy": "return [{json: new Proxy({}, {get() { throw new Error('p'); }, ownKeys() { throw new Error('k'); }})}];",
    "aninhamento_100k": "let o = {}; let c = o; for (let i = 0; i < 100000; i++) { c.a = {}; c = c.a; } return [{json: o}];",
    "nan_infinity": "return [{json: {a: NaN, b: Infinity, c: -Infinity, d: undefined}}];",
    "proto_no_json": "return [{json: JSON.parse('{\"__proto__\": {\"x\": 1}, \"constructor\": 2}')}];",
    "item_string": "return [{json: 'texto'}];",
    "item_numero": "return [1, 2, 3];",
    "retorna_null": "return null;",
    "retorna_numero": "return 5;",
    "retorna_undefined": "return;",
    "chave_gigante": "const o = {}; o['k'.repeat(1000000)] = 1; return [{json: o}];",
    "milhao_de_itens": "return Array.from({length: 1000000}, (_, i) => ({json: {i}}));",
    "saida_acima_de_5mb": "return [{json: {x: 'y'.repeat(6000000)}}];",
    "lancar_objeto": "throw {message: 'obj', stack: '/Users/x/segredo.js'};",
    "lancar_string": "throw 'texto solto';",
    "sintaxe_invalida": "return (",
}


@pytest.mark.parametrize("nome", sorted(RETORNOS_HOSTIS))
def test_retorno_hostil_nunca_derruba_a_execucao_nem_vaza_caminho(nome, rodar_no):
    """MV2-18 C5b/d, SEG-17: retornos hostis (toJSON/getters que lançam, circular, BigInt, Symbol, função, Proxy, aninhamento de
    100 mil níveis, 1 milhão de itens, > 5 MB, throw de objeto) → sucesso (saneado) ou erro `codigo`/`codigo_limite`/`limite_itens`;
    nunca 500, rápido, e a mensagem não expõe caminho de arquivo nem pilha."""
    t0 = time.time()
    e, _ = rodar_no("codigo", cod(RETORNOS_HOSTIS[nome]), [{"a": 1}])
    assert e is not None and e.status in ("sucesso", "erro")
    assert time.time() - t0 < 30
    from django.apps import apps
    n = apps.get_model("execucoes", "ExecucaoNo").objects.get(execucao=e, no_id="t")
    if n.status == "erro":
        assert n.erro_categoria in ("codigo", "codigo_limite", "limite_itens"), n.erro_categoria
        for ruim in ("/Users", "/home/", "node_modules", "runner", "Traceback", "at Object", "\\\\"):
            assert ruim not in (n.erro_mensagem or ""), (ruim, n.erro_mensagem)
