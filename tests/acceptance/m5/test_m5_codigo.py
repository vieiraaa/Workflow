"""Aceite M5 parte C: nó Código (NOV-06, SEG-17). Contrato: MV2-18 C5. Por comportamento observável.

Fugas do vm provadas pelo Revisor de Segurança ficam em tests/adversarial/test_revisao_seguranca.py (não duplicadas aqui).
"""

import json
import time

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]


def cod(codigo, modo="uma_vez_para_todos"):
    return {"modo": modo, "codigo": codigo}


# ---------------- API e retorno ----------------

def test_para_todos_recebe_todos_os_itens(rodar_no):
    """NOV-06: uma_vez_para_todos com $input.all()."""
    _, (s,) = rodar_no("codigo", cod("return $input.all().map(i => ({json: {dobro: i.json.n * 2}}));"), [{"n": 1}, {"n": 2}, {"n": 3}])
    assert s == [{"dobro": 2}, {"dobro": 4}, {"dobro": 6}]


def test_por_item_roda_uma_vez_por_item_com_json(rodar_no):
    """NOV-06: uma_vez_por_item usa $json do item atual."""
    _, (s,) = rodar_no("codigo", cod("return {json: {r: $json.n + 1}};", "uma_vez_por_item"), [{"n": 1}, {"n": 10}])
    assert s == [{"r": 2}, {"r": 11}]


def test_atalhos_input_first_last_item_e_items_legado(rodar_no):
    """NOV-06: $input.first()/.last()/.all(), items (legado)."""
    ent = [{"x": 1}, {"x": 2}, {"x": 3}]
    codigo = ("return [{json: {p: $input.first().json.x, u: $input.last().json.x, n: $input.all().length, "
              "legado: items.length, l0: items[0].json.x}}];")
    _, (s,) = rodar_no("codigo", cod(codigo), ent)
    assert s == [{"p": 1, "u": 3, "n": 3, "legado": 3, "l0": 1}]
    _, (s,) = rodar_no("codigo", cod("return {json: {i: $input.item.json.x}};", "uma_vez_por_item"), ent)
    assert [j["i"] for j in s] == [1, 2, 3]


def test_referencia_a_outro_no_pelo_titulo(rodar_no):
    """NOV-06: $('Título').first()/.last()/.all()/.item."""
    codigo = "return [{json: {a: $('Dados').first().json.x, b: $('Dados').last().json.x, c: $('Dados').all().length}}];"
    _, (s,) = rodar_no("codigo", cod(codigo), [{"x": 1}, {"x": 5}])
    assert s == [{"a": 1, "b": 5, "c": 2}]


def test_variaveis_de_contexto_e_datas_nativas(rodar_no, usuario_adm):
    """NOV-06: $now/$today são Date nativo; $execution.id, $workflow.name, $parametros."""
    codigo = ("return [{json: {agora: $now instanceof Date, hoje: $today instanceof Date, ms: typeof $now.getTime(), "
              "exec: String($execution.id), wf: $workflow.name, par: typeof $parametros}}];")
    e, (s,) = rodar_no("codigo", cod(codigo), [{}])
    j = s[0]
    assert e.status == "sucesso", e.erro_resumo
    assert j["agora"] is True and j["hoje"] is True and j["ms"] == "number" and j["exec"] == str(e.pk)
    assert j["wf"] == e.fluxo_nome and j["par"] == "object"


def test_objetos_soltos_sao_embrulhados(rodar_no):
    """NOV-06: retorno com objetos sem 'json' é embrulhado; objeto único também."""
    _, (s,) = rodar_no("codigo", cod("return [{a: 1}, {json: {b: 2}}];"), [{}])
    assert s == [{"a": 1}, {"b": 2}]
    _, (s,) = rodar_no("codigo", cod("return {c: 3};"), [{}])
    assert s == [{"c": 3}]


def test_spread_map_filter_e_dedupe_do_javascript_completo(rodar_no):
    """NOV-06/D-021: JavaScript de verdade (Map, spread, filter, reduce, Date, regex, template)."""
    codigo = """
    const u = [...new Map($input.all().map(i => [i.json.id, i.json])).values()];
    const total = u.reduce((a, c) => a + c.v, 0);
    return [{json: {ids: u.map(x => x.id), total, t: `n=${u.length}`, d: new Date(Date.UTC(2026, 9, 9)).toISOString().slice(0, 10), re: /^a+$/.test('aaa')}}];
    """
    _, (s,) = rodar_no("codigo", cod(codigo), [{"id": 1, "v": 2}, {"id": 2, "v": 3}, {"id": 1, "v": 2}])
    assert s == [{"ids": [1, 2], "total": 5, "t": "n=2", "d": "2026-10-09", "re": True}]


def test_console_log_capturado_ate_200_linhas(rodar_no, no):
    """NOV-06/C5a: logs = lista de strings (args unidos por espaço), máx. 200."""
    e, _ = rodar_no("codigo", cod("console.log('a', 1, 'b'); for (let i = 0; i < 250; i++) console.log('l' + i); return [{json: {}}];"), [{}])
    logs = no(e, "t").logs
    assert e.status == "sucesso" and logs[0] == "a 1 b" and len(logs) == 200


def test_throw_vira_erro_codigo_com_a_mensagem(rodar_no, no):
    """NOV-06/C5b: throw → erro 'codigo' com a mensagem do Error; execução erro."""
    e, _ = rodar_no("codigo", cod("throw new Error('Falhou de propósito');"), [{}])
    assert e.status == "erro" and no(e, "t").erro_categoria == "codigo" and "Falhou de propósito" in no(e, "t").erro_mensagem


@pytest.mark.parametrize("codigo", ["return 5;", "return 'texto';", "const x = 1;", "return null;", "return [1, 2];", "return [{json: 1}];",
                                    "return {{ ;", "return foo.bar;"])
def test_retorno_invalido_ou_sintaxe_quebrada_e_erro_codigo(codigo, rodar_no, no):
    """NOV-06/C5b: retorno que não é array/objeto, itens inválidos, erro de sintaxe ou de referência → erro 'codigo' (nunca 500)."""
    e, _ = rodar_no("codigo", cod(codigo), [{}])
    assert e.status == "erro" and no(e, "t").erro_categoria == "codigo"


def test_erro_do_codigo_respeita_em_erro_continuar(rodar_no, no):
    """MV2-05+NOV-06: em_erro=continuar entrega o item com json.erro e a execução segue."""
    e, (s,) = rodar_no("codigo", cod("throw new Error('x');", "uma_vez_por_item"), [{"a": 1}], em_erro="continuar")
    assert e.status == "sucesso" and s[0]["a"] == 1 and s[0]["erro"]["categoria"] == "codigo"


def test_codigo_de_mais_de_50000_caracteres_e_pendencia(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-06: codigo ≤ 50.000 chars; 50.001 = pendência (200)."""
    f = fabrica_fluxo(grafo=h.cadeia2())

    def grafo(n):
        return h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("c", "codigo", cod("//" + "a" * (n - 2)), x=1)], [("g", "c")])
    assert salvar_grafo(cliente_adm, f, grafo(50000)).json()["pendencias"] == []
    r = salvar_grafo(cliente_adm, f, grafo(50001))
    assert r.status_code == 200 and r.json()["pendencias"]


# ---------------- limites (C5d) ----------------

def test_laco_infinito_estoura_cpu_em_ate_uns_5s(rodar_no, no):
    """NOV-06/SEG-17: 5 s de CPU → erro 'codigo_limite'; o servidor não trava."""
    t = time.monotonic()
    e, _ = rodar_no("codigo", cod("while (true) {}"), [{}])
    assert e.status == "erro" and no(e, "t").erro_categoria == "codigo_limite" and time.monotonic() - t < 20


def test_memoria_acima_de_128mb_e_codigo_limite(rodar_no, no):
    """NOV-06/SEG-17: estouro de memória → 'codigo_limite'."""
    e, _ = rodar_no("codigo", cod("const a = []; while (true) a.push(new Array(1e6).fill(1.5));"), [{}])
    assert e.status == "erro" and no(e, "t").erro_categoria == "codigo_limite"


def test_saida_acima_de_5mb_e_codigo_limite(rodar_no, no):
    """NOV-06/SEG-17: saída > 5 MB → 'codigo_limite'; saída de ~1 MB passa."""
    e, (s,) = rodar_no("codigo", cod("return [{json: {x: 'a'.repeat(1024 * 1024)}}];"), [{}])
    assert e.status == "sucesso" and len(s[0]["x"]) == 1024 * 1024
    e, _ = rodar_no("codigo", cod("return [{json: {x: 'a'.repeat(6 * 1024 * 1024)}}];"), [{}])
    assert e.status == "erro" and no(e, "t").erro_categoria == "codigo_limite"


def test_log_gigante_nao_trava_nem_estoura_historico(rodar_no, no):
    """SEG-17: console.log em laço (milhões de linhas) é contido: ou sucesso com ≤200 logs ou erro de limite, em tempo limitado."""
    t = time.monotonic()
    e, _ = rodar_no("codigo", cod("for (let i = 0; i < 3e6; i++) console.log('x'.repeat(100)); return [{json: {}}];"), [{}])
    n = no(e, "t")
    assert time.monotonic() - t < 30
    assert (e.status == "sucesso" and len(n.logs) <= 200) or n.erro_categoria == "codigo_limite"


# ---------------- isolamento por comportamento (SEG-17, C5e) ----------------

NOMES_PROIBIDOS = ["process", "require", "fetch", "WebSocket", "setTimeout", "setInterval", "setImmediate", "XMLHttpRequest",
                   "module", "exports", "__dirname", "Deno", "Bun", "WebAssembly.instantiate"]


def _passou_ou_barrou(e, no, chave="r"):
    """Isolado = o nó errou com categoria 'codigo' OU o código viu 'undefined'/'bloqueado' (nunca um objeto/função)."""
    n = no(e, "t")
    if e.status == "erro":
        return n.erro_categoria == "codigo", n
    return all(j[chave] in ("undefined", "bloqueado") for j in [i["json"] for i in n.saida]), n


@pytest.mark.parametrize("nome", NOMES_PROIBIDOS)
def test_globais_perigosos_nao_existem(nome, rodar_no, no):
    """SEG-17: process/require/fetch/WebSocket/timers… indefinidos ou inacessíveis."""
    e, _ = rodar_no("codigo", cod(f"let r; try {{ r = typeof ({nome}); }} catch (x) {{ r = 'bloqueado'; }} return [{{json: {{r}}}}];"), [{}])
    ok, n = _passou_ou_barrou(e, no)
    assert ok, [i["json"] for i in n.saida]


@pytest.mark.parametrize("truque", [
    "this.constructor.constructor('return process')()",
    "(function () { return this; })().process",
    "globalThis.process",
    "[].constructor.constructor('return globalThis.process')()",
    "(() => {}).constructor('return process')()",
    "Object.getPrototypeOf(async function () {}).constructor('return process')()",
    "require('child_process')", "require('fs')", "require('net')", "require('os')",
    "process.binding('fs')", "process.mainModule.require('fs')",
])
def test_truques_de_fuga_comuns_nao_entregam_capacidade(truque, rodar_no, no):
    """SEG-17: truques clássicos de fuga do vm não entregam process/require ao código."""
    codigo = f"let r; try {{ const v = {truque}; r = typeof v === 'undefined' ? 'undefined' : 'VAZOU:' + typeof v; }} catch (x) {{ r = 'bloqueado'; }} return [{{json: {{r}}}}];"
    e, _ = rodar_no("codigo", cod(codigo), [{}])
    ok, n = _passou_ou_barrou(e, no)
    assert ok, [i["json"] for i in n.saida]


def test_sem_rede_nenhuma_requisicao_chega_ao_servidor_local(rodar_no, liberado, no):
    """SEG-17: fetch/http/net/WebSocket do código não alcançam nem um servidor local liberado ao motor."""
    url = f"{liberado.base}/vazou"
    codigo = f"""
    const tentativas = [
      () => fetch('{url}'),
      () => require('http').get('{url}'),
      () => require('net').connect({liberado.porta}, '127.0.0.1'),
      () => new WebSocket('ws://127.0.0.1:{liberado.porta}/ws'),
      () => new XMLHttpRequest().open('GET', '{url}'),
    ];
    for (const t of tentativas) {{ try {{ t(); }} catch (e) {{}} }}
    return [{{json: {{fim: true}}}}];
    """
    rodar_no("codigo", cod(codigo), [{}])
    time.sleep(0.5)
    assert liberado.requisicoes == []


def test_sem_sistema_de_arquivos(rodar_no, tmp_path, no):
    """SEG-17: o código não lê arquivos do servidor (arquivo marcador não aparece em nenhuma saída)."""
    marcador = "MARCADOR-ARQUIVO-FICTICIO-7788"
    alvo = tmp_path / "segredo.txt"
    alvo.write_text(marcador)
    codigo = f"let r = 'nada'; for (const m of ['fs', 'node:fs', 'fs/promises']) {{ try {{ r = require(m).readFileSync('{alvo}', 'utf8'); }} catch (e) {{}} }} return [{{json: {{r}}}}];"
    e, _ = rodar_no("codigo", cod(codigo), [{}])
    from django.apps import apps
    todo = json.dumps(list(apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e).values("saida", "erro_mensagem", "entrada")), default=str)
    assert marcador not in todo and marcador not in (e.erro_resumo or "")


def test_sem_variaveis_de_ambiente_do_servidor(rodar_no, monkeypatch):
    """SEG-17: variáveis de ambiente do processo Django não chegam ao código."""
    monkeypatch.setenv("SEGREDO_AMBIENTE_TESTE_C5", "ENV-VALOR-FICTICIO-9911")
    codigo = ("let r = 'nada'; try { r = JSON.stringify(process.env); } catch (e) {} "
              "try { r += JSON.stringify(Object.keys(globalThis)); } catch (e) {} return [{json: {r}}];")
    e, _ = rodar_no("codigo", cod(codigo), [{}])
    from django.apps import apps
    todo = json.dumps(list(apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e).values("saida", "erro_mensagem")), default=str)
    assert "ENV-VALOR-FICTICIO-9911" not in todo and "ENV-VALOR-FICTICIO-9911" not in (e.erro_resumo or "")


def test_estado_nao_vaza_entre_execucoes(rodar_no):
    """SEG-17: um processo por execução de nó — globais definidas numa execução não existem na seguinte."""
    rodar_no("codigo", cod("globalThis.vazamento_entre_execucoes = 'SIM'; return [{json: {}}];"), [{}])
    _, (s,) = rodar_no("codigo", cod("return [{json: {v: typeof globalThis.vazamento_entre_execucoes}}];"), [{}])
    assert s == [{"v": "undefined"}]


def test_codigo_nao_altera_os_itens_de_entrada_do_historico(rodar_no, no):
    """NOV-06: mutar $input no código não corrompe a entrada gravada (entrada e saída são cópias JSON)."""
    e, _ = rodar_no("codigo", cod("$input.all()[0].json.n = 999; return [{json: {ok: true}}];"), [{"n": 1}])
    assert no(e, "t").entrada[0]["json"] == {"n": 1}


# ---------------- só Adm cria/edita (C5c) ----------------

@pytest.fixture
def grafo_com_codigo(h):
    def _g(codigo="return [{json: {a: 1}}];", desativado=False, extra_titulo="Código"):
        return h.grafo2([h.no2("g", "gatilho", titulo="Início"),
                         h.no2("c", "codigo", cod(codigo), x=1, titulo=extra_titulo, desativado=desativado)], [("g", "c")])
    return _g


MSG = "Só o administrador pode criar ou editar o nó Código."


def test_coordenador_nao_adiciona_nem_altera_codigo(logar, setor_a, fluxo_no_setor, salvar_grafo, grafo_com_codigo, h):
    """NOV-06/C5c: Coordenador que adiciona ou altera nó Código recebe 403 JSON e nada é gravado."""
    cli, _ = logar("Coordenador", setor_a)
    f = fluxo_no_setor(setor_a, grafo=h.cadeia2())
    antes = f.grafo
    r = salvar_grafo(cli, f, grafo_com_codigo())
    assert r.status_code == 403 and r.json()["ok"] is False and r.json()["erros"] == [{"campo": None, "mensagem": MSG}]
    f.refresh_from_db()
    assert f.grafo == antes


@pytest.mark.parametrize("mudanca", ["codigo", "desativado", "tipo"])
def test_coordenador_nao_altera_codigo_existente(mudanca, logar, setor_a, fluxo_no_setor, salvar_grafo, grafo_com_codigo, h):
    """NOV-06/C5c: alterar config, desativado ou o tipo de um nó Código existente é recusado."""
    cli, _ = logar("Coordenador", setor_a)
    f = fluxo_no_setor(setor_a, grafo=grafo_com_codigo())
    novo = grafo_com_codigo()
    if mudanca == "codigo":
        novo["nos"][1]["config"]["codigo"] = "return [{json: {a: 2}}];"
    elif mudanca == "desativado":
        novo["nos"][1]["desativado"] = True
    else:
        novo["nos"][1]["tipo"] = "sem_operacao"
        novo["nos"][1]["config"] = {}
    original = f.grafo
    r = salvar_grafo(cli, f, novo)
    assert r.status_code == 403 and r.json()["erros"][0]["mensagem"] == MSG
    f.refresh_from_db()
    assert f.grafo == original


def test_coordenador_salva_fluxo_com_codigo_sem_mexer_nele(logar, setor_a, fluxo_no_setor, salvar_grafo, grafo_com_codigo, h):
    """NOV-06/C5c: salvar mexendo só em outros nós passa; mover o nó Código também passa (posição não é config)."""
    cli, _ = logar("Coordenador", setor_a)
    f = fluxo_no_setor(setor_a, grafo=grafo_com_codigo())
    novo = grafo_com_codigo()
    novo["nos"].append(h.no2("s", "sem_operacao", x=5))
    novo["arestas"].append(h.aresta("c", "s"))
    novo["nos"][1]["posicao"] = {"x": 777, "y": 5}
    r = salvar_grafo(cli, f, novo)
    assert r.status_code == 200 and r.json()["ok"] is True
    f.refresh_from_db()
    assert len(f.grafo["nos"]) == 3


def test_adm_cria_e_altera_codigo(cliente_adm, fabrica_fluxo, salvar_grafo, grafo_com_codigo, h):
    """NOV-06/C5c: Adm pode."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    assert salvar_grafo(cliente_adm, f, grafo_com_codigo()).status_code == 200
    assert salvar_grafo(cliente_adm, f, grafo_com_codigo("return [{json: {a: 9}}];")).status_code == 200


def test_todos_os_papeis_executam_fluxo_com_codigo(logar, setor_a, fluxo_no_setor, grafo_com_codigo, modelos):
    """NOV-06/C5c: Coordenador e Base (com acesso) executam fluxo que tem Código."""
    f = fluxo_no_setor(setor_a, grafo=grafo_com_codigo(), status="ativo")
    for papel in ("Coordenador", "Base"):
        cli, _ = logar(papel, setor_a)
        r = cli.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
        assert r.status_code == 302
    assert list(modelos.Execucao.objects.values_list("status", flat=True)) == ["sucesso", "sucesso"]
