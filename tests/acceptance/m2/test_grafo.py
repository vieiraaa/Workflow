"""Aceite M2: salvar grafo e editor. Fontes: GRF-01..07, GRF-04, FLX-05, SEG-12, SEG-14, PRM-01/02/03/08."""
import copy
import json
import re

import pytest
from django.apps import apps
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _Fluxo():
    return apps.get_model("fluxos", "Fluxo")


def _url(f):
    return reverse("fluxos:salvar_grafo", kwargs={"pk": f.pk})


def _http(grafo):
    return grafo["nos"][1]


def _salvo(f):
    f.refresh_from_db()
    return f.grafo


# ---------- GRF-01: contrato e permissões ----------

@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador"])
def test_salvar_grafo_valido(request, cliente, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-01: ok=true, pendencias=[], grafo gravado."""
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [], "arestas": []})
    r = salvar_grafo(request.getfixturevalue(cliente), f, grafo_valido)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["ok"] is True and corpo["pendencias"] == []
    assert _salvo(f) == grafo_valido


@pytest.mark.modulo("m2")
def test_salvar_grafo_permissoes(cliente_base, cliente_anonimo, cliente_adm, fabrica_fluxo, grafo_valido, salvar_grafo):
    """PRM-01/02/03/08: Base 403, anônimo login, pk inexistente 404, GET 405; nada gravado."""
    f = fabrica_fluxo(status="ativo", grafo={"versao": 1, "nos": [], "arestas": []})
    assert salvar_grafo(cliente_base, f, grafo_valido).status_code == 403
    r = salvar_grafo(cliente_anonimo, f, grafo_valido)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert cliente_adm.get(_url(f)).status_code == 405
    inexistente = copy.copy(f)
    inexistente.pk = 999999
    assert salvar_grafo(cliente_adm, inexistente, grafo_valido, atualizado_em="2000-01-01T00:00:00+00:00").status_code == 404
    assert _salvo(f) == {"versao": 1, "nos": [], "arestas": []}


@pytest.mark.modulo("m2")
def test_salvar_grafo_exige_csrf(usuario_adm, fabrica_fluxo, grafo_valido):
    """GRF-01/SEG-12: sem X-CSRFToken → 403; com token válido → 200."""
    from django.test import Client
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [], "arestas": []})
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    corpo = json.dumps({"grafo": grafo_valido, "atualizado_em": f.atualizado_em.isoformat()})
    assert c.post(_url(f), corpo, content_type="application/json").status_code == 403
    assert _salvo(f) == {"versao": 1, "nos": [], "arestas": []}
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',
                      c.get(reverse("fluxos:lista")).content.decode())
    if token is None:
        pytest.skip("lista sem formulário com token: não dá para obter token pela UI")
    r = c.post(_url(f), corpo, content_type="application/json", HTTP_X_CSRFTOKEN=token.group(1))
    assert r.status_code == 200


# ---------- GRF-02: erros de formato (400, nada gravado) ----------

def _mut(fn):
    def aplicar(g):
        fn(g)
        return g
    return aplicar


FORMATO = {
    "versao_2": _mut(lambda g: g.update(versao=2)),
    "sem_versao": _mut(lambda g: g.pop("versao")),
    "tipo_desconhecido": _mut(lambda g: g["nos"][1].update(tipo="python")),
    "id_repetido": _mut(lambda g: g["nos"][2].update(id="n1")),
    "id_com_espaco": _mut(lambda g: g["nos"][0].update(id="n 1")),
    "id_vazio": _mut(lambda g: g["nos"][0].update(id="")),
    "id_41_caracteres": _mut(lambda g: g["nos"][0].update(id="a" * 41)),
    "id_com_barra": _mut(lambda g: g["nos"][0].update(id="a/b")),
    "aresta_para_inexistente": _mut(lambda g: g["arestas"].append({"de": "n1", "para": "zzz"})),
    "aresta_de_inexistente": _mut(lambda g: g["arestas"].append({"de": "zzz", "para": "n1"})),
    "nos_nao_e_lista": _mut(lambda g: g.update(nos="n1")),
    "arestas_nao_e_lista": _mut(lambda g: g.update(arestas={"de": "n1"})),
    "titulo_numero": _mut(lambda g: g["nos"][0].update(titulo=123)),
    "posicao_texto": _mut(lambda g: g["nos"][0].update(posicao={"x": "a", "y": 1})),
    "config_lista": _mut(lambda g: g["nos"][1].update(config=[])),
    "no_nao_objeto": _mut(lambda g: g["nos"].append("n9")),
    "id_numerico": _mut(lambda g: g["nos"][0].update(id=7)),
}


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("nome", sorted(FORMATO))
def test_formato_invalido_400_nada_gravado(nome, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-02: erro de formato → 400, ok=false, grafo anterior intacto."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    r = salvar_grafo(cliente_coordenador, f, FORMATO[nome](grafo_valido))
    assert r.status_code == 400, nome
    assert r.json()["ok"] is False
    assert _salvo(f) == antes


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("bruto", ["{nao e json", "", "[]", "null", '{"grafo": 1, "atualizado_em": "x"}',
                                    '{"atualizado_em": "x"}', '"texto"'])
def test_corpo_malformado_400(bruto, cliente_adm, fabrica_fluxo, salvar_grafo):
    """GRF-02: JSON inválido ou estrutura errada → 400 (nunca 500), nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    r = salvar_grafo(cliente_adm, f, None, bruto=bruto)
    assert r.status_code == 400
    assert _salvo(f) == antes


@pytest.mark.modulo("m2")
def test_payload_acima_de_256kb_400(cliente_adm, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-02/SEG-14: payload > 256 KB → 400 e nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    _http(grafo_valido)["titulo"] = "t" * (270 * 1024)
    r = salvar_grafo(cliente_adm, f, grafo_valido)
    assert r.status_code == 400
    assert _salvo(f) == antes


@pytest.mark.modulo("m2")
def test_mais_de_50_nos_400_e_50_aceito(cliente_adm, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-02: 51 nós → 400; exatamente 50 → aceito como formato (pendências não impedem salvar)."""
    f = fabrica_fluxo()
    def com_n(n):
        g = copy.deepcopy(grafo_valido)
        g["nos"] += [{"id": f"x{i}", "tipo": "saida", "titulo": "S", "posicao": {"x": 0, "y": 0}, "config": {}}
                     for i in range(n - 3)]
        return g
    antes = copy.deepcopy(f.grafo)
    assert salvar_grafo(cliente_adm, f, com_n(51)).status_code == 400
    assert _salvo(f) == antes
    r = salvar_grafo(cliente_adm, f, com_n(50))
    assert r.status_code == 200 and r.json()["ok"] is True


@pytest.mark.modulo("m2")
def test_id_com_40_caracteres_e_aceito(cliente_adm, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-02 (limite): id com 40 caracteres e hífen/sublinhado é válido."""
    f = fabrica_fluxo()
    longo = "a" * 38 + "-_"
    grafo_valido["nos"][0]["id"] = longo
    grafo_valido["arestas"][0]["de"] = longo
    r = salvar_grafo(cliente_adm, f, grafo_valido)
    assert r.status_code == 200 and r.json()["ok"] is True


# ---------- GRF-03: pendências ----------

def _sem(grafo, tipo):
    grafo["nos"] = [n for n in grafo["nos"] if n["tipo"] != tipo]
    ids = {n["id"] for n in grafo["nos"]}
    grafo["arestas"] = [a for a in grafo["arestas"] if a["de"] in ids and a["para"] in ids]
    return grafo


def _no(id_, tipo, config=None):
    return {"id": id_, "tipo": tipo, "titulo": id_, "posicao": {"x": 0, "y": 0}, "config": config or {}}


PENDENCIAS = {
    "sem_gatilho": lambda g: _sem(g, "gatilho"),
    "dois_gatilhos": lambda g: (g["nos"].append(_no("g2", "gatilho")), g["arestas"].append({"de": "g2", "para": "n2"}), g)[-1],
    "sem_saida": lambda g: _sem(g, "saida"),
    "no_solto": lambda g: (g["nos"].append(_no("solto", "saida")), g)[-1],
    "ciclo": lambda g: (g["arestas"].append({"de": "n3", "para": "n2"}), g)[-1],
    "duas_saidas_de_um_no": lambda g: (g["nos"].append(_no("s2", "saida")), g["arestas"].append({"de": "n2", "para": "s2"}), g)[-1],
    "duas_entradas_em_um_no": lambda g: (g["nos"].append(_no("g2", "gatilho")), g["arestas"].append({"de": "g2", "para": "n3"}), g)[-1],
    "gatilho_com_entrada": lambda g: (g["arestas"].append({"de": "n2", "para": "n1"}), g)[-1],
    "saida_com_saida": lambda g: (g["nos"].append(_no("s2", "saida")), g["arestas"].append({"de": "n3", "para": "s2"}), g)[-1],
    "grafo_vazio": lambda g: {"versao": 1, "nos": [], "arestas": []},
}


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("nome", sorted(PENDENCIAS))
def test_pendencia_nao_impede_salvar_rascunho(nome, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-03: pendência → 200, ok=true, pendencias listadas (com no/campo/mensagem) e grafo gravado."""
    f = fabrica_fluxo()
    g = PENDENCIAS[nome](grafo_valido)
    r = salvar_grafo(cliente_coordenador, f, g)
    assert r.status_code == 200, nome
    corpo = r.json()
    assert corpo["ok"] is True and corpo["pendencias"], nome
    for p in corpo["pendencias"]:
        assert {"no", "campo", "mensagem"} <= set(p) and p["mensagem"]
    assert _salvo(f) == g


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("nome", sorted(PENDENCIAS))
def test_pendencia_impede_ativar(nome, cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-03/FLX-04: cada pendência impede ativar."""
    f = fabrica_fluxo(grafo=PENDENCIAS[nome](grafo_valido))
    r = cliente_coordenador.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"},
                                 HTTP_ACCEPT="application/json")
    assert r.status_code == 400 and r.json()["ok"] is False
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_pendencia_aponta_o_no(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-05/GRF-01: pendência de configuração referencia o id do nó; global usa no=null."""
    f = fabrica_fluxo()
    _http(grafo_valido)["config"]["metodo"] = "TRACE"
    corpo = salvar_grafo(cliente_coordenador, f, grafo_valido).json()
    assert any(p["no"] == "n2" for p in corpo["pendencias"])
    f2 = fabrica_fluxo()
    corpo = salvar_grafo(cliente_coordenador, f2, _sem(copy.deepcopy(grafo_valido), "saida")).json()
    assert any(p["no"] is None for p in corpo["pendencias"])


# ---------- GRF-04: configuração do nó http ----------

def _cfg(**kw):
    def aplicar(g):
        _http(g)["config"].update(kw)
        return g
    return aplicar


def _titulo(t):
    def aplicar(g):
        _http(g)["titulo"] = t
        return g
    return aplicar


CONFIG_INVALIDA = {
    "metodo_invalido": _cfg(metodo="TRACE"),
    "metodo_minusculo_fora_da_lista": _cfg(metodo=""),
    "url_vazia": _cfg(url=""),
    "url_2049": _cfg(url="https://exemplo.test/" + "a" * (2049 - 21)),
    "url_ftp": _cfg(url="ftp://exemplo.test/x"),
    "url_file": _cfg(url="file:///etc/passwd"),
    "url_javascript": _cfg(url="javascript:alert(1)"),
    "url_sem_host": _cfg(url="http:///caminho"),
    "url_sem_esquema": _cfg(url="exemplo.test/x"),
    "headers_31": _cfg(headers=[{"nome": f"H{i}", "valor": "v"} for i in range(31)]),
    "query_31": _cfg(query=[{"nome": f"q{i}", "valor": "v"} for i in range(31)]),
    "header_nome_vazio": _cfg(headers=[{"nome": "", "valor": "v"}]),
    "header_nome_com_espaco": _cfg(headers=[{"nome": "X Y", "valor": "v"}]),
    "header_nome_com_crlf": _cfg(headers=[{"nome": "X\r\nY", "valor": "v"}]),
    "header_valor_com_crlf": _cfg(headers=[{"nome": "X", "valor": "a\r\nInjetado: 1"}]),
    "header_valor_4097": _cfg(headers=[{"nome": "X", "valor": "v" * 4097}]),
    "query_valor_com_lf": _cfg(query=[{"nome": "q", "valor": "a\nb"}]),
    "corpo_json_invalido": _cfg(metodo="POST", corpo="{nao json"),
    "corpo_em_get": _cfg(metodo="GET", corpo='{"a": 1}'),
    "corpo_em_delete": _cfg(metodo="DELETE", corpo='{"a": 1}'),
    "corpo_acima_de_100kb": _cfg(metodo="POST", corpo=json.dumps({"a": "x" * (101 * 1024)})),
    "titulo_vazio": _titulo(""),
    "titulo_81": _titulo("t" * 81),
}


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("nome", sorted(CONFIG_INVALIDA))
def test_config_invalida_vira_pendencia_no_no(nome, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-04/GRF-03: configuração inválida = pendência do nó n2 (salva, mas não ativa)."""
    f = fabrica_fluxo()
    g = CONFIG_INVALIDA[nome](grafo_valido)
    r = salvar_grafo(cliente_coordenador, f, g)
    if r.status_code == 400:
        pytest.fail(f"{nome}: spec GRF-03 diz que config inválida é pendência (200), não erro de formato")
    corpo = r.json()
    assert corpo["ok"] is True
    assert any(p["no"] == "n2" for p in corpo["pendencias"]), nome


VALIDAS = {
    "url_http_maiusculo": _cfg(url="HTTP://api.exemplo.test/x"),
    "url_https_misto": _cfg(url="HtTpS://api.exemplo.test/x"),
    "url_com_placeholder": _cfg(url="https://api.exemplo.test/pedidos/{{ anterior.corpo.id }}"),
    "url_2048": _cfg(url="https://exemplo.test/" + "a" * (2048 - 21)),
    "headers_30": _cfg(headers=[{"nome": f"H{i}", "valor": "v"} for i in range(30)]),
    "header_valor_4096": _cfg(headers=[{"nome": "X", "valor": "v" * 4096}]),
    "post_com_corpo_json": _cfg(metodo="POST", corpo='{"a": "{{ anterior.status }}"}'),
    "put_corpo_vazio": _cfg(metodo="PUT", corpo=""),
    "patch_com_corpo": _cfg(metodo="PATCH", corpo='{"x": 1}'),
    "titulo_80": _titulo("t" * 80),
    "titulo_unicode": _titulo("Consulta ção 😀"),
}


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("nome", sorted(VALIDAS))
def test_config_valida_sem_pendencias(nome, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-04 (limites válidos): sem pendências."""
    f = fabrica_fluxo()
    r = salvar_grafo(cliente_coordenador, f, VALIDAS[nome](grafo_valido))
    assert r.status_code == 200 and r.json()["pendencias"] == [], nome


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("metodo", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_todos_os_metodos_validos(metodo, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-04: GET|POST|PUT|PATCH|DELETE são aceitos."""
    f = fabrica_fluxo()
    r = salvar_grafo(cliente_coordenador, f, _cfg(metodo=metodo)(grafo_valido))
    assert r.status_code == 200 and r.json()["pendencias"] == []


# ---------- GRF-06 / GRF-07 / editor ----------

@pytest.mark.modulo("m2")
def test_ida_e_volta_identica(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-06: salvar e recarregar o editor devolve o mesmo grafo canônico."""
    f = fabrica_fluxo()
    grafo_valido["nos"][1]["titulo"] = "Título com acentuação ção 😀"
    grafo_valido["nos"][1]["posicao"] = {"x": 12.5, "y": -40}
    assert salvar_grafo(cliente_coordenador, f, grafo_valido).status_code == 200
    html = cliente_coordenador.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).content.decode()
    m = re.search(r'<script id="grafo-inicial" type="application/json">(.*?)</script>', html, re.S)
    assert m, "json_script id=grafo-inicial ausente"
    assert json.loads(m.group(1)) == grafo_valido


@pytest.mark.modulo("m2")
def test_editor_permissoes(cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo, fabrica_fluxo):
    """FLX-05/PRM-01/02/03: editor 200 para Adm/Coord, 403 Base, login anônimo, 404 inexistente."""
    f = fabrica_fluxo(status="ativo")
    url = reverse("fluxos:editor", kwargs={"pk": f.pk})
    assert cliente_adm.get(url).status_code == 200
    assert cliente_coordenador.get(url).status_code == 200
    assert cliente_base.get(url).status_code == 403
    r = cliente_anonimo.get(url)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert cliente_coordenador.get(reverse("fluxos:editor", kwargs={"pk": 999999})).status_code == 404


@pytest.mark.modulo("m2")
def test_editor_expoe_atualizado_em_iso(cliente_adm, fabrica_fluxo):
    """FLX-06: editor entrega `atualizado_em` em ISO-8601 na página."""
    f = fabrica_fluxo()
    html = cliente_adm.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).content.decode()
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", html)


@pytest.mark.modulo("m2")
def test_concorrencia_409(cliente_adm, cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-07: salvar com atualizado_em velho → 409 com a mensagem exata, sem sobrescrever."""
    f = fabrica_fluxo()
    lido = f.atualizado_em.isoformat()  # o que as duas pessoas leram ao abrir
    primeiro = copy.deepcopy(grafo_valido)
    primeiro["nos"][1]["titulo"] = "Edição da pessoa A"
    assert salvar_grafo(cliente_adm, f, primeiro, atualizado_em=lido).status_code == 200
    segundo = copy.deepcopy(grafo_valido)
    segundo["nos"][1]["titulo"] = "Edição da pessoa B"
    r = salvar_grafo(cliente_coordenador, f, segundo, atualizado_em=lido)
    assert r.status_code == 409
    assert "Este fluxo foi alterado por outra pessoa. Recarregue para continuar." in r.content.decode()
    assert _salvo(f)["nos"][1]["titulo"] == "Edição da pessoa A"


@pytest.mark.modulo("m2")
def test_edicao_de_nome_tambem_invalida_atualizado_em_antigo(cliente_adm, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-07: se o fluxo mudou depois (ex.: renomeado), o token antigo é recusado."""
    f = fabrica_fluxo()
    lido = f.atualizado_em.isoformat()
    cliente_adm.post(reverse("fluxos:editar", kwargs={"pk": f.pk}), {"nome": "Renomeado", "descricao": ""})
    r = salvar_grafo(cliente_adm, f, grafo_valido, atualizado_em=lido)
    assert r.status_code == 409


@pytest.mark.modulo("m2")
def test_save_com_token_atual_sequencial_funciona(cliente_adm, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-07 (controle): com o atualizado_em atual do banco, salvar funciona repetidamente."""
    f = fabrica_fluxo()
    for i in range(3):
        grafo_valido["nos"][1]["titulo"] = f"Versão {i}"
        assert salvar_grafo(cliente_adm, f, grafo_valido).status_code == 200
    assert _salvo(f)["nos"][1]["titulo"] == "Versão 2"
