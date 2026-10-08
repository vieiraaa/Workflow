import copy
import json

import pytest

from apps.fluxos.grafo import validar
from apps.fluxos.models import grafo_inicial

pytestmark = pytest.mark.modulo("m2")


def _valido():
    return {
        "versao": 1,
        "nos": [
            {
                "id": "n1",
                "tipo": "gatilho",
                "titulo": "Início",
                "posicao": {"x": 1, "y": 2},
                "config": {},
            },
            {
                "id": "n2",
                "tipo": "http",
                "titulo": "Buscar",
                "posicao": {"x": 3, "y": 4},
                "config": {
                    "metodo": "GET",
                    "url": "https://api.exemplo.test/x",
                    "headers": [{"nome": "Accept", "valor": "application/json"}],
                    "query": [],
                    "corpo": "",
                },
            },
            {
                "id": "n3",
                "tipo": "saida",
                "titulo": "Fim",
                "posicao": {"x": 5, "y": 6},
                "config": {},
            },
        ],
        "arestas": [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n3"}],
    }


def _com(alterar):
    grafo = _valido()
    alterar(grafo)
    return grafo


def _no(id_, tipo, **config):
    return {"id": id_, "tipo": tipo, "titulo": id_, "posicao": {"x": 0, "y": 0}, "config": config}


def test_grafo_valido_e_grafo_inicial():
    assert validar(_valido()) == ([], [])
    erros, pendencias = validar(grafo_inicial())
    assert erros == []
    assert [p["no"] for p in pendencias] == [None]  # falta saída


@pytest.mark.parametrize(
    "grafo",
    [
        None,
        [],
        "x",
        {},
        _com(lambda g: g.update(versao=2)),
        _com(lambda g: g.update(versao=True)),
        _com(lambda g: g.update(nos="n1")),
        _com(lambda g: g.update(arestas={})),
        _com(lambda g: g["nos"][0].update(id="n 1")),
        _com(lambda g: g["nos"][0].update(id=7)),
        _com(lambda g: g["nos"][2].update(id="n1")),
        _com(lambda g: g["nos"][1].update(tipo="python")),
        _com(lambda g: g["nos"][0].update(titulo=1)),
        _com(lambda g: g["nos"][0].update(posicao={"x": True, "y": 1})),
        _com(lambda g: g["nos"][0].update(posicao={"x": 1})),
        _com(lambda g: g["nos"][0].update(config=[])),
        _com(lambda g: g["nos"].append("x")),
        _com(lambda g: g["arestas"].append({"de": "n1", "para": "zzz"})),
        _com(lambda g: g["arestas"].append({"de": 1, "para": "n1"})),
        _com(lambda g: g["arestas"].append("x")),
        _com(lambda g: g["nos"][1]["config"].update(headers="x")),
        _com(lambda g: g["nos"][1]["config"].update(query={"a": "b"})),
        _com(lambda g: g["nos"][1]["config"].update(headers=[{"valor": "v"}])),
        _com(lambda g: g["nos"][1]["config"].update(headers=[{"nome": "X", "valor": 1}])),
        _com(lambda g: g["nos"][1]["config"].update(url=5)),
    ],
)
def test_erros_de_formato(grafo):
    erros, pendencias = validar(grafo)
    assert erros and pendencias == []
    assert all({"campo", "mensagem"} <= set(e) for e in erros)


def test_limite_de_50_nos():
    grafo = _valido()
    grafo["nos"] += [_no(f"x{i}", "saida") for i in range(47)]
    assert validar(grafo)[0] == []
    grafo["nos"].append(_no("x99", "saida"))
    assert validar(grafo)[0]


def _msgs(grafo):
    return validar(grafo)[1]


def _remover(grafo, id_):
    grafo["nos"] = [n for n in grafo["nos"] if n["id"] != id_]
    grafo["arestas"] = [a for a in grafo["arestas"] if id_ not in (a["de"], a["para"])]


ESTRUTURA = {
    "sem_gatilho": (lambda g: _remover(g, "n1"), None),
    "dois_gatilhos": (lambda g: g["nos"].append(_no("g2", "gatilho")), None),
    "sem_saida": (lambda g: _remover(g, "n3"), None),
    "no_solto": (lambda g: g["nos"].append(_no("solto", "saida")), "solto"),
    "ciclo": (lambda g: g["arestas"].append({"de": "n3", "para": "n2"}), "n2"),
    "auto_laco": (lambda g: g["arestas"].append({"de": "n2", "para": "n2"}), "n2"),
    "duas_saidas": (
        lambda g: (
            g["nos"].append(_no("s2", "saida")),
            g["arestas"].append({"de": "n2", "para": "s2"}),
        ),
        "n2",
    ),
    "duas_entradas": (
        lambda g: (
            g["nos"].append(_no("g2", "gatilho")),
            g["arestas"].append({"de": "g2", "para": "n3"}),
        ),
        "n3",
    ),
    "gatilho_com_entrada": (lambda g: g["arestas"].append({"de": "n2", "para": "n1"}), "n1"),
    "saida_com_saida": (
        lambda g: (
            g["nos"].append(_no("s2", "saida")),
            g["arestas"].append({"de": "n3", "para": "s2"}),
        ),
        "n3",
    ),
}


@pytest.mark.parametrize("nome", sorted(ESTRUTURA))
def test_pendencias_de_estrutura(nome):
    alterar, no = ESTRUTURA[nome]
    grafo = _valido()
    alterar(grafo)
    pendencias = _msgs(grafo)
    assert pendencias
    if no:
        assert any(p["no"] == no for p in pendencias)
    assert all({"no", "campo", "mensagem"} <= set(p) and p["mensagem"] for p in pendencias)


def test_grafo_vazio_tem_pendencias_globais():
    pendencias = _msgs({"versao": 1, "nos": [], "arestas": []})
    assert len(pendencias) == 2 and all(p["no"] is None for p in pendencias)


def _http(**config):
    def alterar(grafo):
        grafo["nos"][1]["config"].update(config)

    return alterar


INVALIDAS = {
    "metodo": _http(metodo="TRACE"),
    "metodo_vazio": _http(metodo=""),
    "url_vazia": _http(url=""),
    "url_longa": _http(url="https://e.test/" + "a" * 2040),
    "ftp": _http(url="ftp://e.test/x"),
    "sem_esquema": _http(url="e.test/x"),
    "sem_host": _http(url="http:///x"),
    "colchete_aberto": _http(url="http://[::1/x"),
    "headers_31": _http(headers=[{"nome": f"H{i}", "valor": "v"} for i in range(31)]),
    "header_nome_vazio": _http(headers=[{"nome": "", "valor": "v"}]),
    "header_nome_espaco": _http(headers=[{"nome": "X Y", "valor": "v"}]),
    "header_valor_crlf": _http(headers=[{"nome": "X", "valor": "a\r\nb"}]),
    "header_valor_grande": _http(headers=[{"nome": "X", "valor": "v" * 4097}]),
    "query_lf": _http(query=[{"nome": "q", "valor": "a\nb"}]),
    "corpo_invalido": _http(metodo="POST", corpo="{x"),
    "corpo_em_get": _http(corpo="{}"),
    "corpo_grande": _http(metodo="POST", corpo=json.dumps({"a": "x" * 110_000})),
}


@pytest.mark.parametrize("nome", sorted(INVALIDAS))
def test_config_http_invalida(nome):
    grafo = _valido()
    INVALIDAS[nome](grafo)
    assert any(p["no"] == "n2" for p in _msgs(grafo))


VALIDAS = {
    "maiusculo": _http(url="HTTPS://e.test/x"),
    "placeholder": _http(url="https://e.test/{{ anterior.corpo.id }}"),
    "url_2048": _http(url="https://e.test/" + "a" * (2048 - 15)),
    "headers_30": _http(headers=[{"nome": f"H{i}", "valor": "v"} for i in range(30)]),
    "post_json": _http(metodo="POST", corpo='{"a": "{{ anterior.status }}"}'),
    "corpo_so_espacos_em_get": _http(corpo="   "),
    "userinfo_nao_e_host": _http(url="https://u@e.test/x"),
}


@pytest.mark.parametrize("nome", sorted(VALIDAS))
def test_config_http_valida(nome):
    grafo = _valido()
    VALIDAS[nome](grafo)
    assert _msgs(grafo) == []


@pytest.mark.parametrize("titulo", ["", "   ", "t" * 81])
def test_titulo_invalido_em_qualquer_no(titulo):
    for indice in (0, 1, 2):
        grafo = _valido()
        grafo["nos"][indice]["titulo"] = titulo
        assert any(p["campo"] == "titulo" for p in _msgs(grafo))


def test_titulo_80_e_unicode_validos():
    grafo = _valido()
    grafo["nos"][0]["titulo"] = "t" * 80
    grafo["nos"][1]["titulo"] = "Consulta ção 😀"
    assert _msgs(grafo) == []


def test_nao_altera_o_grafo_recebido():
    grafo = _valido()
    copia = copy.deepcopy(grafo)
    validar(grafo)
    assert grafo == copia


# ---------------------------------------------------------------- GRF-09
def _aninhar(niveis):
    valor = []
    for _ in range(niveis):
        valor = [valor]
    return valor


@pytest.mark.parametrize(
    "alterar",
    [
        lambda g: g.update(extra=1),
        lambda g: g["nos"][0].update(extra=1),
        lambda g: g["nos"][0]["posicao"].update(z=1),
        lambda g: g["nos"][0]["config"].update(extra=1),  # gatilho: config fechada e vazia
        lambda g: g["nos"][2]["config"].update(extra=1),  # saída
        lambda g: g["nos"][1]["config"].update(extra=1),  # http
        lambda g: g["arestas"][0].update(extra=1),
        lambda g: g["nos"][1]["config"]["headers"][0].update(extra="x"),
    ],
)
def test_chave_desconhecida_e_formato(alterar):
    grafo = _valido()
    alterar(grafo)
    erros, pendencias = validar(grafo)
    assert pendencias == [] and any("Chave desconhecida" in e["mensagem"] for e in erros)


def test_profundidade_maxima_16():
    grafo = _valido()
    grafo["nos"][1]["config"]["metodo"] = "GET"
    assert validar(grafo)[0] == []
    grafo["extra"] = _aninhar(14)  # raiz(1) + 15 listas = 16 níveis → ainda permitido
    assert not any("aninhamento" in e["mensagem"] for e in validar(grafo)[0])
    grafo["extra"] = _aninhar(15)  # 17 níveis
    assert any("aninhamento" in e["mensagem"] for e in validar(grafo)[0])


def test_aninhamento_extremo_nao_estoura_a_pilha():
    grafo = _valido()
    grafo["extra"] = _aninhar(100_000)
    erros, _ = validar(grafo)
    assert any("aninhamento" in e["mensagem"] for e in erros)


@pytest.mark.parametrize("numero", [float("nan"), float("inf"), float("-inf")])
def test_numero_nao_finito(numero):
    grafo = _valido()
    grafo["nos"][0]["posicao"]["x"] = numero
    assert any("número inválido" in e["mensagem"] for e in validar(grafo)[0])


@pytest.mark.parametrize("texto", ["a\ud800b", "a\x00b"])
def test_texto_invalido_no_valor_e_na_chave(texto):
    grafo = _valido()
    grafo["nos"][0]["titulo"] = texto
    assert any("texto inválido" in e["mensagem"] for e in validar(grafo)[0])
    grafo = _valido()
    grafo["nos"][0]["config"] = {texto: 1}
    assert any("texto inválido" in e["mensagem"] for e in validar(grafo)[0])
