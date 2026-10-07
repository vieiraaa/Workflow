"""Aceite M2: grafo canônico fechado. Fonte: GRF-09 (a: chave desconhecida, b: profundidade, c: não finitos, d: UTF-8/NUL)."""

import copy
import json

import pytest

pytestmark = pytest.mark.django_db


def _no(g, i=1):
    return g["nos"][i]


def _nao_grava_e_explica(r, f, antes):
    assert r.status_code == 400, r.status_code
    corpo = r.json()
    assert corpo["ok"] is False
    assert corpo["erros"] and all(e.get("mensagem") for e in corpo["erros"])
    f.refresh_from_db()
    assert f.grafo == antes


def _bruto(f, grafo_json):
    return '{"grafo": GRAFO, "atualizado_em": "TOKEN"}'.replace("GRAFO", grafo_json).replace(
        "TOKEN", f.atualizado_em.isoformat()
    )


# ---------- (a) chave desconhecida em qualquer nível ----------

DESCONHECIDAS = {
    "raiz": lambda g: g.update(extra=1),
    "raiz_status": lambda g: g.update(status="ativo"),
    "no_gatilho": lambda g: g["nos"][0].update(extra=1),
    "no_http": lambda g: g["nos"][1].update(extra=1),
    "no_saida": lambda g: g["nos"][2].update(extra=1),
    "no_class": lambda g: g["nos"][0].update(__class__="x"),
    "aresta": lambda g: g["arestas"][0].update(peso=1),
    "posicao": lambda g: g["nos"][0]["posicao"].update(z=1),
    "config_gatilho": lambda g: g["nos"][0]["config"].update(extra=1),
    "config_http": lambda g: g["nos"][1]["config"].update(timeout=5),
    "config_saida": lambda g: g["nos"][2]["config"].update(extra=1),
    "header_item": lambda g: g["nos"][1]["config"]["headers"][0].update(extra=1),
    "query_item": lambda g: g["nos"][1]["config"]["query"][0].update(extra=1),
}


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("onde", sorted(DESCONHECIDAS))
def test_chave_desconhecida_e_400_de_formato(
    onde, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo
):
    """GRF-09(a): chave desconhecida em raiz, nó, aresta, posicao ou config → 400, nada gravado, mensagem clara."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    DESCONHECIDAS[onde](grafo_valido)
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    _nao_grava_e_explica(r, f, antes)


@pytest.mark.modulo("m2")
def test_grafo_so_com_chaves_conhecidas_continua_valido(
    cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo
):
    """GRF-09(a) controle: o exemplo canônico (só chaves conhecidas) segue sendo salvo."""
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [], "arestas": []})
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200 and r.json()["ok"] is True


# ---------- (b) profundidade máxima 16 ----------


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("profundidade", [17, 40, 2000, 100000])
def test_profundidade_acima_de_16_e_400(profundidade, cliente_coordenador, fabrica_fluxo):
    """GRF-09(b): aninhamento > 16 → 400 (nunca 500), nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    aninhado = "[" * profundidade + "]" * profundidade
    bruto = _bruto(f, '{"versao": 1, "nos": [], "arestas": [], "extra": ' + aninhado + "}")
    r = cliente_coordenador.post(_url(f), bruto, content_type="application/json")
    _nao_grava_e_explica(r, f, antes)


@pytest.mark.modulo("m2")
def test_profundidade_dentro_do_posicao_e_config(cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-09(b): estrutura aninhada dentro de posicao/config (onde só cabem escalares/listas de pares) → 400."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    fundo = "[" * 50 + "]" * 50
    g = json.dumps(grafo_valido).replace('"x": 80', '"x": ' + fundo, 1)
    r = cliente_coordenador.post(_url(f), _bruto(f, g), content_type="application/json")
    _nao_grava_e_explica(r, f, antes)


def _url(f):
    from django.urls import reverse

    return reverse("fluxos:salvar_grafo", kwargs={"pk": f.pk})


# ---------- (c) números não finitos ----------


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("num", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999", "1E400"])
@pytest.mark.parametrize("campo", ["x", "y"])
def test_numero_nao_finito_e_400(num, campo, cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-09(c): NaN, Infinity, -Infinity e overflow (1e999) em posicao → 400, nunca 500, nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    grafo_valido["nos"][0]["posicao"] = {"x": 0, "y": 0}
    g = json.dumps(grafo_valido).replace(f'"{campo}": 0', f'"{campo}": {num}', 1)
    r = cliente_coordenador.post(_url(f), _bruto(f, g), content_type="application/json")
    _nao_grava_e_explica(r, f, antes)


@pytest.mark.modulo("m2")
def test_numeros_finitos_extremos_ainda_valem(
    cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo
):
    """GRF-09(c) controle: coordenadas negativas, decimais e grandes-mas-finitas são aceitas."""
    f = fabrica_fluxo()
    grafo_valido["nos"][0]["posicao"] = {"x": -1234.5, "y": 1e10}
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200 and r.json()["ok"] is True


# ---------- (d) UTF-8 sem surrogate e sem NUL ----------


def _com(grafo, onde, valor):
    g = copy.deepcopy(grafo)
    if onde == "titulo":
        g["nos"][1]["titulo"] = valor
    elif onde == "url":
        g["nos"][1]["config"]["url"] = "https://api.exemplo.test/" + valor
    elif onde == "header_valor":
        g["nos"][1]["config"]["headers"] = [{"nome": "X-A", "valor": valor}]
    elif onde == "header_nome":
        g["nos"][1]["config"]["headers"] = [{"nome": "X" + valor, "valor": "v"}]
    elif onde == "query_valor":
        g["nos"][1]["config"]["query"] = [{"nome": "q", "valor": valor}]
    elif onde == "corpo":
        g["nos"][1]["config"].update(metodo="POST", corpo='{"a": "' + valor + '"}')
    elif onde == "id":
        g["nos"][0]["id"] = "n" + valor
        g["arestas"][0]["de"] = "n" + valor
    return g


ONDE = ["titulo", "url", "header_valor", "header_nome", "query_valor", "corpo", "id"]


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("onde", ONDE)
def test_nul_em_string_e_400(onde, cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-09(d): NUL (\\u0000) em qualquer string → 400 (nunca 500), nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    g = _com(grafo_valido, onde, "a\u0000b")
    r = cliente_coordenador.post(
        _url(f),
        json.dumps({"grafo": g, "atualizado_em": f.atualizado_em.isoformat()}),
        content_type="application/json",
    )
    _nao_grava_e_explica(r, f, antes)


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("onde", ONDE)
@pytest.mark.parametrize("surrogate", ["\\ud800", "\\udc00", "\\ud83d"])
def test_surrogate_solto_e_400(onde, surrogate, cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-09(d): surrogate solto (alto sem baixo, baixo sozinho) em qualquer string → 400, nunca 500."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    marcador = "MARCADOR"
    g = json.dumps(_com(grafo_valido, onde, marcador)).replace(marcador, surrogate)
    r = cliente_coordenador.post(_url(f), _bruto(f, g), content_type="application/json")
    _nao_grava_e_explica(r, f, antes)


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("onde", ["titulo", "header_valor", "query_valor", "corpo"])
def test_unicode_valido_continua_aceito(
    onde, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo
):
    """GRF-09(d) controle: acentos, CJK, emoji (par surrogate válido) e zero-width são aceitos e gravados intactos."""
    f = fabrica_fluxo()
    g = _com(grafo_valido, onde, "Ação 日本語 😀 a​b")
    r = salvar_grafo(cliente_coordenador, f, g)
    assert r.status_code == 200 and r.json()["ok"] is True
    f.refresh_from_db()
    assert f.grafo == g


@pytest.mark.modulo("m2")
def test_par_surrogate_valido_escapado_e_emoji(cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-09(d) controle: \\ud83d\\ude00 (par válido escapado) vira o emoji e é aceito."""
    f = fabrica_fluxo()
    g = json.dumps(_com(grafo_valido, "titulo", "MARCADOR")).replace("MARCADOR", "\\ud83d\\ude00")
    r = cliente_coordenador.post(_url(f), _bruto(f, g), content_type="application/json")
    assert r.status_code == 200
    f.refresh_from_db()
    assert f.grafo["nos"][1]["titulo"] == "😀"
