"""Adversarial M5: importação (IMP-02/04, SEG-19, MV2-18 C6–C8). JSON externo é dado não confiável."""

import json

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaWN0aWNpbyJ9.assinaturaficticia1234567890abc"
CHAVE = "Kq7Zp3Xv9Lm2Nb5Tc8Rd1Sg4Hj6Wf0Yz3AaBbCcDd"
BEARER = "Bearer abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture
def simples(imp):
    return imp.n8n([imp.n8n_no("Início", "manualTrigger"), imp.n8n_no("Fim", "noOp", pos=(200, 0))], [imp.liga("Início", ["Fim"])])


def _nada_criado(imp, antes):
    assert imp.novos(antes).count() == 0


# ---------------- permissões e CSRF ----------------

def test_base_e_anonimo_nao_importam_e_csrf_e_exigido(cliente_base, cliente_anonimo, usuario_adm, imp, simples):
    """MV2-18 C6: Base 403, anônimo → login; sem CSRF 403; nada criado."""
    from django.test import Client
    antes = imp.pks()
    assert imp.importar(cliente_base, simples).status_code == 403
    r = imp.importar(cliente_anonimo, simples, json_=False)
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(reverse("fluxos:importar"), {"arquivo": imp.arquivo(simples)}).status_code == 403
    assert cliente_base.get(reverse("fluxos:importar")).status_code in (403, 405)
    _nada_criado(imp, antes)


# ---------------- tamanho, profundidade, formato ----------------

def test_arquivo_acima_de_2mb_e_recusado(cliente_adm, imp):
    """SEG-19/IMP-02: > 2 MB → 400, nada criado."""
    antes = imp.pks()
    grande = imp.n8n([imp.n8n_no("A", "manualTrigger")], nome="x" * (2 * 1024 * 1024 + 10))
    r = imp.importar(cliente_adm, grande)
    assert r.status_code == 400 and r.json()["ok"] is False
    _nada_criado(imp, antes)


def test_arquivo_gigante_de_50mb_nao_derruba(cliente_adm, imp):
    """SEG-19: 50 MB de lixo → recusado (4xx) sem 500 nem esgotar memória; nada criado."""
    antes = imp.pks()
    r = imp.importar(cliente_adm, b"{" + b'"a":"' + b"x" * (50 * 1024 * 1024) + b'"}')
    assert 400 <= r.status_code < 500
    _nada_criado(imp, antes)


def _profundidade(o, n=0):
    if isinstance(o, dict):
        return max([_profundidade(v, n + 1) for v in o.values()] + [n + 1])
    if isinstance(o, list):
        return max([_profundidade(v, n + 1) for v in o] + [n + 1])
    return n


@pytest.mark.parametrize("profundidade", [100, 1000, 50000, 500000])
def test_json_profundamente_aninhado_nunca_da_500_e_nada_fundo_e_gravado(profundidade, cliente_adm, imp):
    """SEG-19/GRF-09(b): aninhamento extremo em parâmetro do n8n (RecursionError do parser) → 4xx limpo OU fluxo criado sem o
    lixo (parâmetro desconhecido = ajuste, MV2-20); o grafo gravado nunca passa de 16 níveis; nunca 500."""
    antes = imp.pks()
    fundo = "[" * profundidade + "]" * profundidade
    bruto = ('{"name": "x", "nodes": [{"id": "1", "name": "A", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, '
             '"position": [0, 0], "parameters": {"x": ' + fundo + '}}], "connections": {}}').encode()
    r = imp.importar(cliente_adm, bruto)
    assert r.status_code < 500
    for f in imp.novos(antes):
        assert _profundidade(f.grafo) <= 16 and _profundidade(f.relatorio_importacao) <= 16


@pytest.mark.parametrize("bruto", [
    b"", b"   ", b"\xff\xfe\x00\x00", b"\xef\xbb\xbf{}", b"{", b"[]", b"null", b"123", b'"texto"', b"{}", b'{"nodes": []}',
    b'{"nodes": {}, "connections": {}}', b'{"nodes": "x", "connections": {}}', b'{"nodes": [], "connections": []}',
    b'{"nodes": [1, "a", null, []], "connections": {}}', b'{"name": 5, "nodes": [], "connections": {}}',
    b'{"name": ["a"], "nodes": [], "connections": {}}', b'{"name": null, "nodes": [], "connections": {}}',
    b'{"nodes": [{"name": "A"}], "connections": {}}',
    b'{"nodes": [{"name": 7, "type": "x", "position": "no"}], "connections": {}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp", "position": "str", "parameters": []}], "connections": {}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp", "typeVersion": "x", "position": [NaN, Infinity]}], "connections": {}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp", "position": [1e999, -1e999]}], "connections": {}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp"}], "connections": {"A": {"main": "x"}}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp"}], "connections": {"A": {"main": [[{"node": "ZZZ"}]]}}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp"}], "connections": {"A": {"main": [[{"node": "A", "index": 99999999999}]]}}}',
    b'{"nodes": [{"name": "A", "type": "n8n-nodes-base.noOp"}], "connections": {"A": {"main": [[{"node": "A", "index": -1}]]}}}',
    b'{"nodes": [{"name": "A\\u0000B", "type": "n8n-nodes-base.noOp"}], "connections": {}}',
    b'{"nodes": [{"name": "\\ud800", "type": "n8n-nodes-base.noOp"}], "connections": {}}',
    b'{"nodes": [{"name": "A", "type": "\\u0000"}], "connections": {}}',
    b'{"formato": "construtor-workflows", "versao": 2}', b'{"formato": "construtor-workflows", "versao": 99, "fluxo": {}, "grafo": {}}',
    b'{"formato": "outro", "versao": 2, "fluxo": {"nome": "x", "descricao": ""}, "grafo": {}}',
    b'{"formato": "construtor-workflows", "versao": true, "fluxo": {"nome": "x", "descricao": ""}, "grafo": {}}',
], ids=lambda b: b[:40].decode("latin-1").replace("\n", " "))
def test_json_hostil_nunca_da_500_e_so_cria_fluxo_valido(bruto, cliente_adm, imp, modelos):
    """SEG-19/GRF-09: tipos errados, NaN/Infinity, surrogate, NUL, conexões para nós inexistentes, formato/versão errados → resposta
    4xx limpa OU fluxo criado SANEADO; nunca 500 e nunca estado quebrado."""
    antes = imp.pks()
    r = imp.importar(cliente_adm, bruto)
    assert r.status_code < 500, r.status_code
    for f in imp.novos(antes):
        assert f.grafo["versao"] == 2 and f.status == "rascunho"
        json.dumps(f.grafo)


def test_chaves_duplicadas_no_json_nao_escolhem_dono_nem_status(cliente_adm, cliente_coordenador, usuario_coordenador, setor_b, imp):
    """SEG-19/C8: chaves duplicadas ('fluxo' e 'dono' repetidos, último vale no parser) não permitem escolher dono/setor/status."""
    bruto = ('{"formato": "construtor-workflows", "versao": 2, "fluxo": {"nome": "A", "descricao": ""}, '
             '"fluxo": {"nome": "B", "descricao": "", "dono": 1, "status": "ativo", "setor": ' + str(setor_b.pk) + '}, '
             '"grafo": {"versao": 2, "nos": [], "arestas": [], "notas": [], "dados_fixos": {}}}').encode()
    antes = imp.pks()
    r = imp.importar(cliente_coordenador, bruto)
    assert r.status_code < 500
    for f in imp.novos(antes):
        assert f.dono == usuario_coordenador and f.status == "rascunho" and f.setor == usuario_coordenador.setor


# ---------------- dono/setor/status/id ----------------

@pytest.mark.parametrize("extra", [
    {"owner": 1, "ownerId": 1, "status": "ativo", "setor": 99, "dono": 1, "pk": 1, "id": "999", "active": True,
     "settings": {"setor": 99, "dono": 1}, "staticData": {"dono": 1}, "meta": {"setor": 99}, "tags": [{"name": "setor"}],
     "versionId": "x", "shared": [{"role": "owner"}]},
])
def test_n8n_com_chaves_hostis_na_raiz_e_campos_extras_do_formulario(extra, cliente_coordenador, usuario_coordenador, setor_b, imp, simples):
    """SEG-19/C8: no n8n as chaves extras da raiz são ignoradas; campos extras do POST (setor/dono/status/id) também. Dono = quem
    importou; setor = o dele; rascunho."""
    obj = dict(simples, **extra)
    antes = imp.pks()
    r = imp.importar(cliente_coordenador, obj, setor=setor_b.pk, dono=1, status="ativo", id=1, fluxo=1)
    assert r.status_code in (200, 302), r.content[:200]
    f = imp.novos(antes).get()
    assert (f.dono, f.setor, f.status) == (usuario_coordenador, usuario_coordenador.setor, "rascunho")
    assert f.pk != 999


def test_nativo_nao_aceita_dono_setor_id_status_em_nenhum_nivel(cliente_adm, fabrica_fluxo, imp, h):
    """SEG-19/C8: formato nativo com chave desconhecida na raiz, em 'fluxo', no grafo e nos nós → rejeitado; nada criado."""
    f = fabrica_fluxo(grafo=h.cadeia2(h.no2("a", "sem_operacao", x=1)))
    base = json.loads(imp.exportar(cliente_adm, f).content)
    for mut in (lambda d: d.update(dono=1), lambda d: d["fluxo"].update(setor=1), lambda d: d["fluxo"].update(id=5),
                lambda d: d["fluxo"].update(status="ativo"), lambda d: d["grafo"].update(status="ativo"),
                lambda d: d["grafo"]["nos"][0].update(dono=1), lambda d: d.update(__proto__={"x": 1})):
        antes = imp.pks()
        d = json.loads(json.dumps(base))
        mut(d)
        r = imp.importar(cliente_adm, d)
        assert r.status_code == 400, d.keys()
        _nada_criado(imp, antes)


@pytest.mark.parametrize("nome", ["<script>window.__pwn=1</script>", '"><img src=x onerror=1>', "x" * 5000, "a\x00b", "‮RTL", "\n\r", ""])
def test_nome_do_fluxo_importado_hostil_e_escapado_ou_recusado(nome, cliente_adm, imp, simples):
    """SEG-19: nome hostil (HTML, 5.000 caracteres, NUL, vazio) → recusado ou saneado; nas telas, escapado; nunca 500."""
    antes = imp.pks()
    r = imp.importar(cliente_adm, dict(simples, name=nome), json_=False, )
    assert r.status_code < 500
    lista = cliente_adm.get(reverse("fluxos:lista")).content.decode()
    assert "<script>window.__pwn=1</script>" not in lista and '"><img src=x onerror=1>' not in lista
    for f in imp.novos(antes):
        assert len(f.nome) <= 120 and "\x00" not in f.nome
        assert "<script>window.__pwn=1</script>" not in cliente_adm.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).content.decode()


def test_mais_de_200_nos_no_import_e_recusado(cliente_adm, imp):
    """MV2-02/SEG-19: 201 nós → recusado (4xx); nada criado."""
    nos = [imp.n8n_no(f"N{i}", "noOp", pos=(i, 0)) for i in range(201)]
    antes = imp.pks()
    r = imp.importar(cliente_adm, imp.n8n(nos))
    assert 400 <= r.status_code < 500
    _nada_criado(imp, antes)


def test_titulos_repetidos_vazios_e_enormes_sao_saneados(cliente_adm, imp):
    """MV2-18 C6/MV2-02: títulos repetidos ganham sufixo; vazio/80+ caracteres não derrubam; todos ficam únicos e ≤ 80."""
    nos = [imp.n8n_no("A", "manualTrigger"), imp.n8n_no("A", "noOp", pos=(1, 0)), imp.n8n_no("A", "noOp", pos=(2, 0)),
           imp.n8n_no("T" * 300, "noOp", pos=(3, 0)), imp.n8n_no("T" * 300, "noOp", pos=(4, 0))]
    antes = imp.pks()
    r = imp.importar(cliente_adm, imp.n8n(nos))
    assert r.status_code in (200, 302, 400), r.status_code
    for f in imp.novos(antes):
        tit = [n["titulo"] for n in f.grafo["nos"]]
        assert len(tit) == len(set(tit)) and all(0 < len(t) <= 80 for t in tit)


# ---------------- segredos disfarçados ----------------

def _segredo_em(imp, onde, valor):
    pos = {"headers": {"sendHeaders": True, "headerParameters": {"parameters": [{"name": "X-A", "value": valor}]}},
           "query": {"sendQuery": True, "queryParameters": {"parameters": [{"name": "k", "value": valor}]}},
           "url": {"url": "https://api.exemplo.test/x?token=" + valor if valor == JWT else "https://api.exemplo.test/" + valor},
           "jsonBody": {"sendBody": True, "specifyBody": "json", "jsonBody": '{"t": "' + valor + '"}'}}[onde]
    pos.setdefault("method", "GET")
    pos.setdefault("url", "https://api.exemplo.test/x")
    return imp.n8n([imp.n8n_no("Início", "manualTrigger"), imp.n8n_no("Chama", "httpRequest", pos, pos=(200, 0), versao=4)],
                   [imp.liga("Início", ["Chama"])])


@pytest.mark.parametrize("valor,onde", [
    (JWT, "headers"), (JWT, "query"), (JWT, "url"), (JWT, "jsonBody"),
    (BEARER, "headers"), (BEARER, "query"), (BEARER, "url"), (BEARER, "jsonBody"),
    (CHAVE, "headers"), (CHAVE, "query"),  # chave 32+ só vale como STRING INTEIRA (C7): em url/corpo é lacuna da spec
])
def test_segredo_em_qualquer_campo_nunca_e_gravado(onde, valor, cliente_adm, cliente_coordenador, imp, modelos):
    """IMP-04/C7: JWT, `Bearer …` e chave longa em header/query/url/corpo → substituídos por {{ $credencial }} + pendência; o valor
    original NÃO fica no fluxo, no relatório, nem nas telas (editor, lista, resposta da importação)."""
    antes = imp.pks()
    r = imp.importar(cliente_coordenador, _segredo_em(imp, onde, valor))
    assert r.status_code in (200, 302, 400)
    htmls = r.content.decode()
    for f in imp.novos(antes):
        bruto = json.dumps(f.grafo) + json.dumps(f.relatorio_importacao)
        parte = valor.replace("Bearer ", "")
        assert parte not in bruto, onde
        htmls += cliente_coordenador.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).content.decode()
        htmls += cliente_coordenador.get(reverse("fluxos:lista")).content.decode()
        assert cliente_coordenador.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"}, HTTP_ACCEPT="application/json").status_code == 400
    assert valor.replace("Bearer ", "") not in htmls


def _gravado(f):
    return json.dumps(f.grafo, ensure_ascii=False) + json.dumps(f.relatorio_importacao, ensure_ascii=False)


def test_segredo_em_jscode_vira_literal_e_valor_nao_e_gravado(cliente_adm, imp):
    """IMP-04/C7/MV2-21: segredo em jsCode vira o texto literal "{{ $credencial }}" (+ pendência); o valor original não é gravado."""
    code = imp.n8n_no("Cod", "code", {"mode": "runOnceForAllItems", "jsCode": f"const t = '{JWT}'; return $input.all();"}, pos=(200, 0))
    antes = imp.pks()
    r = imp.importar(cliente_adm, imp.n8n([imp.n8n_no("Início", "manualTrigger"), code], [imp.liga("Início", ["Cod"])]))
    assert r.status_code in (200, 302)
    f = imp.novos(antes).get()
    assert JWT not in _gravado(f) and "{{ $credencial }}" in _gravado(f)


def test_segredo_em_pindata_nao_e_gravado(cliente_adm, imp):
    """IMP-04 ("o valor original não é gravado"): token dentro de pinData (vira dados_fixos, persistido no banco e no export) não
    pode ser gravado em claro."""
    obj = imp.n8n([imp.n8n_no("Início", "manualTrigger"), imp.n8n_no("Fim", "noOp", pos=(200, 0))], [imp.liga("Início", ["Fim"])])
    obj["pinData"] = {"Fim": [{"json": {"token": JWT, "auth": BEARER}}]}
    antes = imp.pks()
    r = imp.importar(cliente_adm, obj)
    assert r.status_code in (200, 302, 400)
    for f in imp.novos(antes):
        assert JWT not in _gravado(f) and "abcdefghijklmnopqrstuvwxyz0123456789" not in _gravado(f)


def test_segredo_em_nota_sticky_nao_e_gravado(cliente_adm, imp):
    """IMP-04 ("o valor original não é gravado"): token no texto de uma nota (stickyNote → notas[].texto) não pode ser gravado em claro."""
    nota = {"id": "n", "name": "Nota", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [0, 100],
            "parameters": {"content": f"token: {JWT}", "width": 100, "height": 100, "color": 1}}
    antes = imp.pks()
    r = imp.importar(cliente_adm, imp.n8n([imp.n8n_no("Início", "manualTrigger"), nota]))
    assert r.status_code in (200, 302, 400)
    for f in imp.novos(antes):
        assert JWT not in _gravado(f)


def test_segredo_com_caracteres_invisiveis_ou_partido_nao_passa_pelo_detector_sem_aviso(cliente_adm, imp):
    """IMP-04 (limite documentado): JWT com zero-width/espaços no meio é a evasão clássica. Exigimos que um token com `\\u200b`
    inserido continue sendo tratado como segredo (substituído) — o valor reconstruído não pode ser gravado."""
    disfarcado = JWT[:20] + "​" + JWT[20:]
    antes = imp.pks()
    r = imp.importar(cliente_adm, _segredo_em(imp, "headers", disfarcado))
    assert r.status_code in (200, 302, 400)
    for f in imp.novos(antes):
        bruto = json.dumps(f.grafo, ensure_ascii=False)
        assert JWT[:20] not in bruto and JWT[20:] not in bruto
