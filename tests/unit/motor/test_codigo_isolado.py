"""T-050: runtime JS isolado do nó Código (SEG-17, NOV-06). Sem banco, sem rede."""

import json
import time
from pathlib import Path

import pytest

from apps.motor.codigo.executor import CodigoErro, executar_codigo

pytestmark = pytest.mark.modulo("m5")

EXEMPLO = (
    Path(__file__).resolve().parents[3] / "docs" / "spec" / "exemplos" / "n8n_chamados_do_dia.json"
)
CONTEXTO = {
    "agora": "2026-10-09T15:00:00.000Z",
    "execucao_id": 7,
    "fluxo_nome": "Chamados",
    "parametros": {"dia": "2026-10-08"},
}


def _codigo(nome):
    dados = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    return next(n["parameters"]["jsCode"] for n in dados["nodes"] if n["name"] == nome)


def test_config_do_exemplo_devolve_um_item():
    saida = executar_codigo(_codigo("Config"), [], contexto=CONTEXTO)
    assert len(saida["itens"]) == 1
    j = saida["itens"][0]["json"]
    assert j["baseUrl"] == "https://eem.digisac.co" and j["porPagina"] == 500
    assert j["fim"] > j["inicio"] and len(j["dia"]) == 10


def test_contexto_do_exemplo_usa_nos_anteriores():
    nos = {
        "Config": [{"json": {"baseUrl": "https://x", "token": "t"}}],
        "Usuário do token": [{"json": {"data": {"id": "u1", "name": "Maggy"}}}],
    }
    saida = executar_codigo(_codigo("Contexto"), [], nos=nos, contexto=CONTEXTO)
    assert saida["itens"] == [
        {"json": {"baseUrl": "https://x", "token": "t", "iaUserId": "u1", "iaNome": "Maggy"}}
    ]


def test_contexto_do_exemplo_erra_sem_id():
    nos = {"Config": [{"json": {}}], "Usuário do token": [{"json": {}}]}
    with pytest.raises(CodigoErro) as e:
        executar_codigo(_codigo("Contexto"), [], nos=nos, contexto=CONTEXTO)
    assert e.value.categoria == "codigo" and "id do usuário" in e.value.mensagem


def test_lista_de_chamados_do_exemplo_junta_paginas_e_deduplica():
    def pagina(ids):
        return {
            "json": {
                "data": [
                    {"id": i, "protocol": f"p{i}", "isOpen": False, "user": {"name": "Ana"}}
                    for i in ids
                ],
                "total": 3,
            }
        }

    saida = executar_codigo(
        _codigo("Lista de chamados"), [pagina([1, 2]), pagina([2, 3])], contexto=CONTEXTO
    )
    assert [i["json"]["ticketId"] for i in saida["itens"]] == [1, 2, 3]
    assert saida["itens"][0]["json"]["atendenteDoChamado"] == "Ana"
    assert saida["itens"][0]["json"]["totalRecebido"] == 3


def test_api_nov06_por_item_e_console():
    codigo = "console.log('oi', $json.n); return {n: $json.n * 2, exec: $execution.id, dia: $parametros.dia, wf: $workflow.name};"
    saida = executar_codigo(
        codigo, [{"json": {"n": 1}}, {"json": {"n": 2}}], modo="uma_vez_por_item", contexto=CONTEXTO
    )
    assert [i["json"]["n"] for i in saida["itens"]] == [2, 4]
    assert saida["itens"][0]["json"]["exec"] == 7 and saida["itens"][0]["json"]["wf"] == "Chamados"
    assert saida["logs"] == ["oi 1", "oi 2"]


def test_api_nov06_input_helpers_e_objeto_solto():
    codigo = "return {a: $input.first().json.v, b: $input.last().json.v, c: $input.all().length, d: items.length};"
    saida = executar_codigo(codigo, [{"json": {"v": 1}}, {"json": {"v": 9}}], contexto=CONTEXTO)
    assert saida["itens"] == [{"json": {"a": 1, "b": 9, "c": 2, "d": 2}}]


FUGAS = {
    "ler_arquivo_require": "return [{json: {x: require('fs').readFileSync('/etc/hosts', 'utf8')}}]",
    "import_dinamico": "return import('node:fs').then((m) => [{json: {x: m.readFileSync('/etc/hosts', 'utf8')}}])",
    "process_env": "return [{json: {x: process.env.PATH}}]",
    "process_binding": "return [{json: {x: process.binding('fs')}}]",
    "child_process": "return [{json: {x: require('child_process').execSync('id').toString()}}]",
    "socket": "return [{json: {x: require('net').connect(80, '1.1.1.1')}}]",
    "fetch": "return [{json: {x: fetch('http://127.0.0.1:1/')}}]",
    "constructor_para_process": "return [{json: {x: this.constructor.constructor('return process')().env}}]",
    "function_constructor": "return [{json: {x: (function(){}).constructor('return process')().env}}]",
    "eval_global": "return [{json: {x: eval('process.env')}}]",
    "console_constructor": "return [{json: {x: console.log.constructor('return process')().env}}]",
    "worker": "return [{json: {x: new Worker('x.js')}}]",
    "global_this_process": "return [{json: {x: globalThis.process.pid}}]",
}


@pytest.mark.parametrize("nome", list(FUGAS))
def test_fuga_bloqueada(nome):
    with pytest.raises(CodigoErro) as e:
        executar_codigo(FUGAS[nome], [], contexto=CONTEXTO)
    assert e.value.categoria == "codigo"


def test_codigo_nao_ve_variaveis_de_ambiente_nem_caminhos():
    saida = executar_codigo(
        "return {t: typeof process, r: typeof require, m: typeof module, i: typeof import_meta}", []
    )
    assert saida["itens"][0]["json"] == {
        "t": "undefined",
        "r": "undefined",
        "m": "undefined",
        "i": "undefined",
    }


def test_laco_infinito_vira_codigo_limite():
    inicio = time.monotonic()
    with pytest.raises(CodigoErro) as e:
        executar_codigo("while (true) {}", [], cpu_s=1)
    assert e.value.categoria == "codigo_limite" and time.monotonic() - inicio < 5


def test_estouro_de_memoria_vira_codigo_limite():
    with pytest.raises(CodigoErro) as e:
        executar_codigo("const a = []; while (true) a.push(new Array(1e6).fill(1));", [], cpu_s=5)
    assert e.value.categoria == "codigo_limite"


def test_saida_acima_de_5mb_vira_codigo_limite():
    with pytest.raises(CodigoErro) as e:
        executar_codigo("return [{json: {x: 'a'.repeat(6 * 1024 * 1024)}}]", [])
    assert e.value.categoria == "codigo_limite"


def test_codigo_acima_de_50000_caracteres_recusado():
    with pytest.raises(CodigoErro):
        executar_codigo("//" + "a" * 50_000, [])


def test_erro_do_usuario_nao_vaza_caminho_do_runtime():
    with pytest.raises(CodigoErro) as e:
        executar_codigo("throw new Error('falhou de propósito')", [])
    assert "falhou de propósito" in e.value.mensagem and "/" not in e.value.mensagem.replace(
        "de propósito", ""
    )


def test_medida_de_partida():
    """Número de referência da recomendação (não é um limite rígido)."""
    tempos = []
    for _ in range(5):
        t = time.monotonic()
        executar_codigo("return [{json: {}}]", [])
        tempos.append((time.monotonic() - t) * 1000)
    print(f"partida Node (mediana de 5): {sorted(tempos)[2]:.0f} ms")
    assert sorted(tempos)[2] < 2000
