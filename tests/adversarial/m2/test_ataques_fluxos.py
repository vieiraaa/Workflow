"""Adversarial M2: IDOR, CSRF, salvar_grafo hostil, XSS, status, placeholders (só sintaxe)."""

import copy
import json

import pytest
from django.apps import apps
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m2")]

XSS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=window.__pwn=1>',
    "'><svg/onload=window.__pwn=1>",
    "</script><script>window.__pwn=1</script>",
    "</title><script>window.__pwn=1</script>",
]


def Fluxo():
    return apps.get_model("fluxos", "Fluxo")


def _h(r):
    return r.content.decode()


def _u(nome, pk):
    return reverse(nome, kwargs={"pk": pk})


def _http(g):
    return g["nos"][1]


def _salvo(f):
    f.refresh_from_db()
    return f.grafo


# ---------- IDOR e escalada ----------

ROTAS_POST = ["fluxos:editar", "fluxos:excluir", "fluxos:status", "fluxos:salvar_grafo"]


@pytest.mark.parametrize("status", ["ativo", "rascunho"])
def test_base_em_todas_as_rotas_de_fluxo(cliente_base, fabrica_fluxo, grafo_valido, status):
    """PRM-02: Base não edita, exclui, muda status nem salva grafo (GET e POST); nada muda."""
    f = fabrica_fluxo(nome="Alvo", status=status)
    antes = copy.deepcopy(f.grafo)
    n = Fluxo().objects.count()
    corpo = json.dumps({"grafo": grafo_valido, "atualizado_em": f.atualizado_em.isoformat()})
    assert cliente_base.get(_u("fluxos:editor", f.pk)).status_code == 403
    assert cliente_base.post(reverse("fluxos:novo"), {"nome": "Invasor"}).status_code == 403
    assert cliente_base.post(_u("fluxos:editar", f.pk), {"nome": "Hack", "descricao": ""}).status_code == 403
    assert cliente_base.post(_u("fluxos:status", f.pk), {"status": "rascunho" if status == "ativo" else "ativo"}).status_code == 403
    assert cliente_base.post(_u("fluxos:salvar_grafo", f.pk), corpo, content_type="application/json").status_code == 403
    assert cliente_base.post(_u("fluxos:excluir", f.pk)).status_code == 403
    for nome in ROTAS_POST:
        assert cliente_base.get(_u(nome, f.pk)).status_code in (403, 405), nome
    f.refresh_from_db()
    assert (f.nome, f.status) == ("Alvo", status) and f.grafo == antes
    assert Fluxo().objects.count() == n


@pytest.mark.parametrize("nome", ["fluxos:editor", *ROTAS_POST])
def test_anonimo_em_todas_as_rotas_de_fluxo(cliente_anonimo, fabrica_fluxo, nome):
    """PRM-01: anônimo → login; nada muda."""
    f = fabrica_fluxo(nome="Intocado")
    metodo = cliente_anonimo.get if nome == "fluxos:editor" else cliente_anonimo.post
    r = metodo(_u(nome, f.pk))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert Fluxo().objects.filter(pk=f.pk, nome="Intocado").exists()


@pytest.mark.parametrize("pk", ["999999", "abc", "-1", "0", "1.5", "99999999999999999999", "%00", "1%20OR%201=1"])
def test_pk_inexistente_ou_malformado_nunca_500(cliente_coordenador, pk):
    """PRM-03: pk inexistente/malformado → 404 em todas as rotas por pk."""
    for nome in ["fluxos:editor", *ROTAS_POST]:
        url = _u(nome, 1).replace("/1/", f"/{pk}/")
        r = cliente_coordenador.get(url) if nome == "fluxos:editor" else cliente_coordenador.post(url, {})
        assert r.status_code == 404, (nome, pk, r.status_code)


def test_base_executar_rascunho_404_e_ativo_nao_vaza(cliente_base, fabrica_fluxo):
    """PRM-03: Base executando rascunho → 404 (idêntico ao pk inexistente)."""
    f = fabrica_fluxo(status="rascunho")
    r1 = cliente_base.post(_u("fluxos:executar", f.pk))
    r2 = cliente_base.post(_u("fluxos:executar", 999999))
    assert r1.status_code == r2.status_code == 404


def test_base_nao_ve_rascunho_na_lista_por_nenhum_parametro(cliente_base, fabrica_fluxo):
    """PRM-04: rascunho nunca aparece para Base, nem com status/q/ordem/pagina forjados."""
    for i in range(30):
        fabrica_fluxo(nome=f"Segredo {i:02d}", status="rascunho")
    fabrica_fluxo(nome="Aberto 00", status="ativo")
    url = reverse("fluxos:lista")
    for params in ({"status": "rascunho"}, {"q": "Segredo"}, {"pagina": 2}, {"ordem": "-nome"}, {"status": ["rascunho", "ativo"]}):
        assert "Segredo 0" not in _h(cliente_base.get(url, params)), params


def test_mass_assignment_em_novo_e_editar(cliente_coordenador, fabrica_fluxo, usuario_adm, usuario_coordenador):
    """Modelo: dono/status/grafo/atualizado_em não são editáveis por POST forjado."""
    cliente_coordenador.post(
        reverse("fluxos:novo"),
        {"nome": "Mass", "descricao": "", "status": "ativo", "dono": usuario_adm.pk, "grafo": '{"versao":1,"nos":[],"arestas":[]}', "atualizado_em": "2000-01-01T00:00:00+00:00"},
    )
    f = Fluxo().objects.get(nome="Mass")
    assert f.status == "rascunho" and f.dono_id == usuario_coordenador.pk
    assert [n["tipo"] for n in f.grafo["nos"]] == ["gatilho"]
    g = fabrica_fluxo(nome="Outro", dono=usuario_adm)
    cliente_coordenador.post(_u("fluxos:editar", g.pk), {"nome": "Outro", "descricao": "", "dono": usuario_coordenador.pk, "status": "ativo", "grafo": "{}"})
    g.refresh_from_db()
    assert g.dono_id == usuario_adm.pk and g.status == "rascunho" and g.grafo["nos"]


def test_salvar_grafo_em_fluxo_excluido_404(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """Estado: salvar grafo depois de excluir o fluxo → 404, nunca 500."""
    f = fabrica_fluxo()
    token = f.atualizado_em.isoformat()
    cliente_coordenador.post(_u("fluxos:excluir", f.pk))
    assert salvar_grafo(cliente_coordenador, f, grafo_valido, atualizado_em=token).status_code == 404


def test_excluir_duas_vezes(cliente_coordenador, fabrica_fluxo):
    """Estado: segunda exclusão do mesmo fluxo → 404."""
    f = fabrica_fluxo()
    assert cliente_coordenador.post(_u("fluxos:excluir", f.pk)).status_code == 302
    assert cliente_coordenador.post(_u("fluxos:excluir", f.pk)).status_code == 404


# ---------- CSRF ----------


def _csrf(u):
    c = Client(enforce_csrf_checks=True)
    c.force_login(u)
    return c


def test_todo_post_do_m2_exige_csrf(usuario_coordenador, fabrica_fluxo, grafo_valido):
    """SEG-12: nenhum POST do M2 funciona sem token."""
    c = _csrf(usuario_coordenador)
    f = fabrica_fluxo(nome="Protegido")
    corpo = json.dumps({"grafo": grafo_valido, "atualizado_em": f.atualizado_em.isoformat()})
    assert c.post(reverse("fluxos:novo"), {"nome": "SemToken"}).status_code == 403
    assert c.post(_u("fluxos:editar", f.pk), {"nome": "Hack", "descricao": ""}).status_code == 403
    assert c.post(_u("fluxos:status", f.pk), {"status": "ativo"}).status_code == 403
    assert c.post(_u("fluxos:salvar_grafo", f.pk), corpo, content_type="application/json").status_code == 403
    assert c.post(_u("fluxos:salvar_grafo", f.pk), corpo, content_type="application/json", HTTP_X_CSRFTOKEN="x" * 64).status_code == 403
    assert c.post(_u("fluxos:excluir", f.pk)).status_code == 403
    f.refresh_from_db()
    assert f.nome == "Protegido" and f.status == "rascunho" and _h(c.get(reverse("fluxos:lista"))) is not None
    assert not Fluxo().objects.filter(nome="SemToken").exists()


# ---------- salvar_grafo hostil ----------


def _post_bruto(c, f, bruto, content_type="application/json"):
    return c.post(_u("fluxos:salvar_grafo", f.pk), bruto, content_type=content_type)


@pytest.mark.parametrize("ct", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "application/xml", ""])
def test_content_type_errado(cliente_coordenador, fabrica_fluxo, grafo_valido, ct):
    """GRF-02: corpo JSON com Content-Type errado nunca dá 500 nem grava."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    corpo = json.dumps({"grafo": grafo_valido, "atualizado_em": f.atualizado_em.isoformat()})
    r = cliente_coordenador.post(_u("fluxos:salvar_grafo", f.pk), corpo, content_type=ct or "application/octet-stream")
    assert r.status_code < 500
    if r.status_code >= 400:
        assert _salvo(f) == antes


def test_json_gigante_acima_de_256kb(cliente_coordenador, fabrica_fluxo, grafo_valido):
    """SEG-14: JSON de 5 MB → 4xx (nunca 500), nada gravado."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    _http(grafo_valido)["config"]["corpo"] = "x" * (5 * 1024 * 1024)
    r = _post_bruto(cliente_coordenador, f, json.dumps({"grafo": grafo_valido, "atualizado_em": f.atualizado_em.isoformat()}))
    assert 400 <= r.status_code < 500
    assert _salvo(f) == antes


@pytest.mark.parametrize("profundidade", [100, 2000, 100000])
def test_json_profundamente_aninhado(cliente_coordenador, fabrica_fluxo, profundidade):
    """GRF-02/SEG-14: aninhamento extremo ([[[...]]]) nunca dá 500 (recursão do parser ou limite de pilha do Postgres)."""
    f = fabrica_fluxo()
    aninhado = "[" * profundidade + "]" * profundidade
    bruto = '{"grafo": {"versao": 1, "nos": [], "arestas": [], "extra": ANINHADO}, "atualizado_em": "TOKEN"}'.replace("ANINHADO", aninhado).replace("TOKEN", f.atualizado_em.isoformat())
    r = _post_bruto(cliente_coordenador, f, bruto)
    assert r.status_code < 500, r.status_code


@pytest.mark.parametrize("num", ["NaN", "Infinity", "-Infinity", "1e999", "9" * 5000])
def test_json_com_numeros_especiais(cliente_coordenador, fabrica_fluxo, num):
    """GRF-02: NaN, Infinity e números gigantes nunca dão 500."""
    f = fabrica_fluxo()
    bruto = (
        '{"grafo": {"versao": 1, "nos": [{"id": "n1", "tipo": "gatilho", "titulo": "t", "posicao": {"x": NUM, "y": 0}, "config": {}}], "arestas": []}, "atualizado_em": "TOKEN"}'
        .replace("NUM", num)
        .replace("TOKEN", f.atualizado_em.isoformat())
    )
    assert _post_bruto(cliente_coordenador, f, bruto).status_code < 500


def test_json_com_chaves_duplicadas(cliente_coordenador, fabrica_fluxo):
    """GRF-02: chave duplicada ("versao": 1 e depois 2) nunca dá 500."""
    f = fabrica_fluxo()
    bruto = '{"grafo": {"versao": 1, "versao": 2, "nos": [], "arestas": []}, "atualizado_em": "TOKEN"}'.replace("TOKEN", f.atualizado_em.isoformat())
    assert _post_bruto(cliente_coordenador, f, bruto).status_code < 500


def test_json_com_surrogate_solto(cliente_coordenador, fabrica_fluxo):
    """GRF-02: surrogate Unicode solto (\\ud800) no título nunca dá 500 (o Postgres recusa esse JSON)."""
    f = fabrica_fluxo()
    bruto = '{"grafo": {"versao": 1, "nos": [{"id": "n1", "tipo": "gatilho", "titulo": "\\ud800", "posicao": {"x": 0, "y": 0}, "config": {}}], "arestas": []}, "atualizado_em": "TOKEN"}'.replace("TOKEN", f.atualizado_em.isoformat())
    assert _post_bruto(cliente_coordenador, f, bruto).status_code < 500


def test_corpo_bytes_invalidos(cliente_coordenador, fabrica_fluxo):
    """GRF-02: corpo com bytes que não são UTF-8 → 400, nunca 500."""
    f = fabrica_fluxo()
    assert _post_bruto(cliente_coordenador, f, b"\xff\xfe\x00bytes").status_code == 400


@pytest.mark.parametrize("id_", ["<script>", "../etc", "a b", "a;b", 'a"b', "ñ", "аdmin", "n1\n", "a" * 41, "", "💥"])
def test_ids_hostis_recusados(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo, id_):
    """GRF-02: id fora de ^[a-zA-Z0-9_-]{1,40}$ (inclusive newline final e homóglifos) → 400."""
    f = fabrica_fluxo()
    antes = copy.deepcopy(f.grafo)
    grafo_valido["nos"][0]["id"] = id_
    grafo_valido["arestas"][0]["de"] = id_
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 400, repr(id_)
    assert _salvo(f) == antes


@pytest.mark.parametrize("id_", ["__proto__", "constructor", "toString", "hasOwnProperty", "prototype"])
def test_ids_perigosos_para_js_sao_salvos_sem_quebrar_o_servidor(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo, id_):
    """GRF-02: ids que casam com a regex (mas são nomes especiais de JS) são válidos; o servidor os guarda intactos."""
    f = fabrica_fluxo()
    grafo_valido["nos"][0]["id"] = id_
    grafo_valido["arestas"][0]["de"] = id_
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200 and r.json()["pendencias"] == []
    assert _salvo(f) == grafo_valido


def test_arestas_duplicadas_auto_aresta_e_ciclo_longo(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-03: arestas duplicadas, auto-aresta e ciclo de 48 nós → pendência (200) ou 400; nunca 500; ativar recusado."""
    casos = {}
    g = copy.deepcopy(grafo_valido)
    g["arestas"].append({"de": "n1", "para": "n2"})
    casos["duplicada"] = g
    g = copy.deepcopy(grafo_valido)
    g["arestas"].append({"de": "n2", "para": "n2"})
    casos["auto"] = g
    g = copy.deepcopy(grafo_valido)
    ring = [{"id": f"h{i}", "tipo": "http", "titulo": "H", "posicao": {"x": i, "y": 0}, "config": {"metodo": "GET", "url": "https://a.exemplo.test/", "headers": [], "query": [], "corpo": ""}} for i in range(48)]
    g["nos"] += ring
    g["arestas"] += [{"de": f"h{i}", "para": f"h{(i + 1) % 48}"} for i in range(48)]
    casos["ciclo_longo"] = g
    for nome, grafo in casos.items():
        f = fabrica_fluxo()
        r = salvar_grafo(cliente_coordenador, f, grafo)
        assert r.status_code in (200, 400), nome
        if r.status_code == 200:
            assert r.json()["pendencias"], nome
            r2 = cliente_coordenador.post(_u("fluxos:status", f.pk), {"status": "ativo"}, HTTP_ACCEPT="application/json")
            assert r2.status_code == 400, nome
            f.refresh_from_db()
            assert f.status == "rascunho"


def test_ciclo_profundo_cadeia_de_50_nos_nao_estoura(cliente_coordenador, fabrica_fluxo, salvar_grafo):
    """GRF-02: cadeia linear de 50 nós (limite) é validada sem 500."""
    nos = [{"id": "g", "tipo": "gatilho", "titulo": "G", "posicao": {"x": 0, "y": 0}, "config": {}}]
    nos += [{"id": f"h{i}", "tipo": "http", "titulo": "H", "posicao": {"x": i, "y": 0}, "config": {"metodo": "GET", "url": "https://a.exemplo.test/", "headers": [], "query": [], "corpo": ""}} for i in range(48)]
    nos += [{"id": "s", "tipo": "saida", "titulo": "S", "posicao": {"x": 99, "y": 0}, "config": {}}]
    ids = [n["id"] for n in nos]
    grafo = {"versao": 1, "nos": nos, "arestas": [{"de": a, "para": b} for a, b in zip(ids, ids[1:], strict=False)]}
    f = fabrica_fluxo()
    r = salvar_grafo(cliente_coordenador, f, grafo)
    assert r.status_code == 200 and r.json()["pendencias"] == []


@pytest.mark.parametrize("token", ["lixo", "", None, 0, [], {}, "9999-12-31T23:59:59+00:00", "2000-01-01T00:00:00+00:00", "2026-13-45T99:99:99", "0001-01-01T00:00:00+00:00", "x" * 10000])
def test_atualizado_em_forjado(cliente_coordenador, fabrica_fluxo, grafo_valido, token):
    """GRF-07: token forjado/antigo/futuro/inválido → 4xx (409 ou 400), nunca 500, nunca grava."""
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [], "arestas": []})
    r = _post_bruto(cliente_coordenador, f, json.dumps({"grafo": grafo_valido, "atualizado_em": token}))
    assert r.status_code in (400, 409), (token, r.status_code)
    assert _salvo(f) == {"versao": 1, "nos": [], "arestas": []}


def test_atualizado_em_ausente(cliente_coordenador, fabrica_fluxo, grafo_valido):
    """GRF-07: sem atualizado_em não dá para sobrescrever às cegas."""
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [], "arestas": []})
    r = _post_bruto(cliente_coordenador, f, json.dumps({"grafo": grafo_valido}))
    assert r.status_code in (400, 409)
    assert _salvo(f) == {"versao": 1, "nos": [], "arestas": []}


def test_corrida_de_dois_salvamentos_com_o_mesmo_token(usuario_adm, usuario_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-07: dois salvamentos com o mesmo atualizado_em → exatamente um 200 e um 409; o segundo não sobrescreve."""
    f = fabrica_fluxo()
    token = f.atualizado_em.isoformat()
    ca, cb = Client(), Client()
    ca.force_login(usuario_adm)
    cb.force_login(usuario_coordenador)
    ga, gb = copy.deepcopy(grafo_valido), copy.deepcopy(grafo_valido)
    ga["nos"][1]["titulo"] = "A"
    gb["nos"][1]["titulo"] = "B"
    codigos = sorted([salvar_grafo(ca, f, ga, atualizado_em=token).status_code, salvar_grafo(cb, f, gb, atualizado_em=token).status_code])
    assert codigos == [200, 409]
    assert _salvo(f)["nos"][1]["titulo"] == "A"


def test_token_reutilizado_apos_salvar_e_409(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-07: reusar o token antigo depois de um save bem-sucedido é recusado (replay)."""
    f = fabrica_fluxo()
    token = f.atualizado_em.isoformat()
    assert salvar_grafo(cliente_coordenador, f, grafo_valido, atualizado_em=token).status_code == 200
    assert salvar_grafo(cliente_coordenador, f, grafo_valido, atualizado_em=token).status_code == 409


def test_campos_extras_no_grafo_nao_sao_gravados_como_estado(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-02: campos desconhecidos no grafo/nó são recusados ou descartados; nunca 500 e nunca alteram status/dono."""
    f = fabrica_fluxo()
    grafo_valido["status"] = "ativo"
    grafo_valido["dono"] = 1
    grafo_valido["nos"][0]["__class__"] = "x"
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code in (200, 400)
    f.refresh_from_db()
    assert f.status == "rascunho"


# ---------- status ----------

PENDENTES = {
    "vazio": {"versao": 1, "nos": [], "arestas": []},
    "so_gatilho": {"versao": 1, "nos": [{"id": "g", "tipo": "gatilho", "titulo": "G", "posicao": {"x": 0, "y": 0}, "config": {}}], "arestas": []},
}


@pytest.mark.parametrize("nome", sorted(PENDENTES))
@pytest.mark.parametrize("accept", ["application/json", "text/html"])
def test_ativar_com_pendencias_por_post_forjado(cliente_coordenador, fabrica_fluxo, nome, accept):
    """FLX-04: POST forjado não ativa fluxo com pendências, com ou sem Accept JSON."""
    f = fabrica_fluxo(grafo=PENDENTES[nome])
    r = cliente_coordenador.post(_u("fluxos:status", f.pk), {"status": "ativo"}, HTTP_ACCEPT=accept)
    assert r.status_code in (400, 302)
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.parametrize("valor", ["ativo ", " ativo", "ATIVO", "Ativo", "1", "true", "arquivado", "ativo\x00", "ativo\nrascunho", "<script>"])
def test_status_valores_invalidos(cliente_coordenador, fabrica_fluxo, valor):
    """GRF-08(d): status fora de rascunho|ativo → 400 e sem alteração."""
    f = fabrica_fluxo(status="rascunho")
    r = cliente_coordenador.post(_u("fluxos:status", f.pk), {"status": valor})
    assert r.status_code == 400
    f.refresh_from_db()
    assert f.status == "rascunho"


def test_status_multivalorado_e_ausente(cliente_coordenador, fabrica_fluxo):
    """GRF-08(d): status repetido ou ausente nunca dá 500; se ativa, só com grafo válido."""
    f = fabrica_fluxo(grafo=PENDENTES["vazio"])
    assert cliente_coordenador.post(_u("fluxos:status", f.pk), {"status": ["rascunho", "ativo"]}).status_code < 500
    assert cliente_coordenador.post(_u("fluxos:status", f.pk), {}).status_code == 400
    f.refresh_from_db()
    assert f.status == "rascunho"


def test_toctou_ativar_e_depois_salvar_grafo_invalido_desativa(cliente_coordenador, fabrica_fluxo, salvar_grafo):
    """EST-01: ativar com grafo válido e salvar um grafo com pendências em seguida nunca deixa fluxo ativo inválido."""
    f = fabrica_fluxo()
    assert cliente_coordenador.post(_u("fluxos:status", f.pk), {"status": "ativo"}).status_code in (200, 302)
    r = salvar_grafo(cliente_coordenador, f, PENDENTES["vazio"])
    assert r.status_code == 200 and r.json()["pendencias"]
    f.refresh_from_db()
    assert f.status == "rascunho"


# ---------- placeholders: só sintaxe ----------

PLH = [
    "{{ __import__('os').system('id') }}",
    "{{ anterior.__class__ }}",
    "{{ anterior.__class__.__mro__[1].__subclasses__() }}",
    "{{ ''.__class__ }}",
    "{{anterior.corpo.a.b.c.d.e.f.g.h.i.j.k.l.m}}",
    "{{ anterior..corpo }}",
    "{{ }}",
    "{{ {{ anterior.corpo }} }}",
    "{% load os %}${7*7}#{7*7}<%= 7*7 %}",
    "{{ anterior.corpo | safe }}",
    "{{" * 1000,
]


@pytest.mark.parametrize("plh", PLH)
def test_placeholders_hostis_so_sintaxe_nao_quebram_o_salvamento(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo, plh):
    """PLH-03: o salvamento nunca interpreta/avalia placeholders (nem 500); o texto é guardado literalmente."""
    f = fabrica_fluxo()
    cfg = _http(grafo_valido)["config"]
    cfg["url"] = "https://api.exemplo.test/x/" + plh
    cfg["headers"] = [{"nome": "X-Teste", "valor": plh}]
    cfg["query"] = [{"nome": "q", "valor": plh}]
    cfg["metodo"] = "POST"
    cfg["corpo"] = json.dumps({"campo": plh})
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200, plh
    saved = _salvo(f)["nos"][1]["config"]
    assert saved["headers"][0]["valor"] == plh and saved["query"][0]["valor"] == plh


def test_placeholder_fora_de_string_no_corpo_e_pendencia(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """GRF-04: placeholder no corpo só dentro de valor string; fora disso o corpo é JSON inválido → pendência no nó."""
    f = fabrica_fluxo()
    cfg = _http(grafo_valido)["config"]
    cfg["metodo"] = "POST"
    cfg["corpo"] = '{"a": {{ anterior.corpo }}}'
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200 and any(p["no"] == "n2" for p in r.json()["pendencias"])


# ---------- XSS no servidor ----------


@pytest.mark.parametrize("payload", XSS)
def test_xss_nome_descricao_na_lista_toasts_e_editor(cliente_coordenador, payload):
    """SEG-13: nome/descrição escapados na lista, nos toasts (criar, atualizar, excluir) e no editor."""
    r = cliente_coordenador.post(reverse("fluxos:novo"), {"nome": payload[:120], "descricao": payload}, follow=True)
    assert payload not in _h(r)
    f = Fluxo().objects.latest("pk")
    assert payload not in _h(cliente_coordenador.get(reverse("fluxos:lista")))
    assert payload not in _h(cliente_coordenador.get(_u("fluxos:editor", f.pk)))
    r = cliente_coordenador.post(_u("fluxos:editar", f.pk), {"nome": payload[:120], "descricao": payload}, follow=True)
    assert payload not in _h(r)
    r = cliente_coordenador.post(_u("fluxos:excluir", f.pk), follow=True)
    assert payload not in _h(r)


@pytest.mark.parametrize("payload", XSS)
def test_xss_no_grafo_no_html_do_editor(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo, payload):
    """SEG-13: título/URL/headers/query/corpo do nó com payload não aparecem crus no HTML do editor (json_script escapa)."""
    f = fabrica_fluxo()
    n = _http(grafo_valido)
    n["titulo"] = payload[:80]
    n["config"]["url"] = "https://api.exemplo.test/" + payload
    n["config"]["headers"] = [{"nome": "X-A", "valor": payload}]
    n["config"]["query"] = [{"nome": "q", "valor": payload}]
    assert salvar_grafo(cliente_coordenador, f, grafo_valido).status_code == 200
    html = _h(cliente_coordenador.get(_u("fluxos:editor", f.pk)))
    assert payload not in html
    assert "</script><script>" not in html


def test_lista_com_nome_e_busca_hostis(cliente_coordenador, fabrica_fluxo):
    """FLX-01: parâmetros e nomes hostis na lista nunca dão 500 (inclui NUL na busca)."""
    for params in ({"q": "\x00"}, {"q": "a" * 10240}, {"ordem": "grafo"}, {"ordem": "dono__password"}, {"status": "x" * 5000}, {"pagina": "9" * 30}):
        assert cliente_coordenador.get(reverse("fluxos:lista"), params).status_code == 200, params


@pytest.mark.parametrize("nome", ["a\x00b", "x" * 100000, "‮RTL", "​​"])
def test_nome_hostil_em_novo(cliente_coordenador, nome):
    """FLX-02: NUL, nome gigante, RTL e zero-width nunca dão 500."""
    assert cliente_coordenador.post(reverse("fluxos:novo"), {"nome": nome, "descricao": ""}).status_code < 500


def test_descricao_gigante_em_novo(cliente_coordenador):
    """FLX-02/SEG-14: descrição de 5 MB → 4xx ou erro de campo, nunca 500."""
    assert cliente_coordenador.post(reverse("fluxos:novo"), {"nome": "Grande", "descricao": "d" * (5 * 1024 * 1024)}).status_code < 500
    assert not Fluxo().objects.filter(nome="Grande").exists()


# ---------- navegador (chromium e webkit): XSS e ids perigosos no editor ----------


def _grafo_xss(payload):
    g = {
        "versao": 1,
        "nos": [
            {"id": "n1", "tipo": "gatilho", "titulo": payload[:80], "posicao": {"x": 80, "y": 100}, "config": {}},
            {"id": "n2", "tipo": "http", "titulo": payload[:80], "posicao": {"x": 360, "y": 100}, "config": {"metodo": "POST", "url": "https://api.exemplo.test/" + payload, "headers": [{"nome": "X-A", "valor": payload}], "query": [{"nome": "q", "valor": payload}], "corpo": json.dumps({"a": payload})}},
            {"id": "n3", "tipo": "saida", "titulo": payload[:80], "posicao": {"x": 640, "y": 100}, "config": {}},
        ],
        "arestas": [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n3"}],
    }
    return g


@pytest.mark.parametrize("payload", XSS)
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_xss_no_editor_nao_executa(pagina_coordenador, fabrica_fluxo, payload):
    """SEG-13: título/URL/headers/query/corpo hostis, no canvas e no inspector, nunca executam script."""
    pagina = pagina_coordenador
    f = fabrica_fluxo(nome=payload[:120], descricao=payload, grafo=_grafo_xss(payload))
    pagina.goto(pagina.live_url + reverse("fluxos:lista"))
    pagina.wait_for_timeout(300)
    pagina.goto(pagina.live_url + _u("fluxos:editor", f.pk))
    pagina.wait_for_selector(".drawflow-node", timeout=10000)
    nos = pagina.locator(".drawflow-node")
    for i in range(nos.count()):
        nos.nth(i).click(position={"x": 8, "y": 8})
        pagina.wait_for_timeout(150)
    pagina.wait_for_timeout(300)
    assert pagina.dialogos == [], pagina.dialogos
    assert pagina.evaluate("window.__pwn") is None
    assert pagina.locator("img[onerror], svg[onload]").count() == 0
    assert not pagina.erros_js, pagina.erros_js


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_editor_carrega_com_ids_proto_e_constructor(pagina_coordenador, fabrica_fluxo):
    """GRF-02/SEG-13: nós com id __proto__ e constructor (válidos pela regex) carregam no canvas sem erro de JS e sem perder nós."""
    pagina = pagina_coordenador
    g = {
        "versao": 1,
        "nos": [
            {"id": "__proto__", "tipo": "gatilho", "titulo": "G", "posicao": {"x": 80, "y": 100}, "config": {}},
            {"id": "constructor", "tipo": "saida", "titulo": "S", "posicao": {"x": 400, "y": 100}, "config": {}},
        ],
        "arestas": [{"de": "__proto__", "para": "constructor"}],
    }
    f = fabrica_fluxo(grafo=g)
    pagina.goto(pagina.live_url + _u("fluxos:editor", f.pk))
    pagina.wait_for_selector(".drawflow-node", timeout=10000)
    assert not pagina.erros_js, pagina.erros_js
    assert pagina.locator(".drawflow-node").count() == 2
    assert pagina.evaluate("({}).polluted") is None
