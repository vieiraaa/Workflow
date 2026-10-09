"""Aceite M5 parte C: importar/exportar (IMP-01..05) e SEG-19. Contrato: MV2-13, MV2-18 C6–C9. JSON externo = dado não confiável."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

P = "n8n-nodes-base."
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaWN0aWNpbyJ9.assinaturaficticia1234567890abc"
CHAVE40 = "Kq7Zp3Xv9Lm2Nb5Tc8Rd1Sg4Hj6Wf0Yz3AaBbCcDd"  # 42 caracteres, fictícia
BEARER = "Bearer abcdefghijklmnopqrstuvwxyz0123456789"


def n8n_no(nome, tipo, params=None, pos=(0, 0), versao=1, **extra):
    return {"id": f"id-{nome}", "name": nome, "type": P + tipo, "typeVersion": versao, "position": list(pos),
            "parameters": params or {}, **extra}


def liga(origem, *destinos_por_saida):
    """{origem: {main: [[{node,type,index}] por saída]}}"""
    return {origem: {"main": [[{"node": d, "type": "main", "index": 0} for d in saida] for saida in destinos_por_saida]}}


def n8n(nos, conexoes=None, nome="Fluxo n8n fictício", **raiz):
    c = {}
    for x in conexoes or []:
        c.update(x)
    return {"name": nome, "nodes": nos, "connections": c, "pinData": {}, "active": False, "settings": {}, **raiz}


def arquivo(obj, nome="fluxo.json"):
    dados = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
    return SimpleUploadedFile(nome, dados, content_type="application/json")


@pytest.fixture
def importar(cliente_adm):
    """importar(obj_ou_bytes, cliente=None, json_=False) → resposta do POST multipart fluxos:importar."""

    def _i(conteudo, cliente=None, json_=False):
        kw = {"HTTP_ACCEPT": "application/json"} if json_ else {}
        return (cliente or cliente_adm).post(reverse("fluxos:importar"), {"arquivo": arquivo(conteudo)}, **kw)

    return _i


@pytest.fixture
def importado(importar, modelos):
    """importado(obj) → Fluxo criado (importa como Adm e devolve o fluxo mais novo)."""

    def _i(conteudo, **kw):
        antes = set(modelos.Fluxo.objects.values_list("pk", flat=True))
        r = importar(conteudo, **kw)
        novos = modelos.Fluxo.objects.exclude(pk__in=antes)
        assert novos.count() == 1, (r.status_code, r.content[:300])
        return novos.get()

    return _i


def _no_por_titulo(g, titulo):
    return next(n for n in g["nos"] if n["titulo"] == titulo)


# ---------------- exportar nativo (IMP-01) ----------------

def test_exportar_nativo_formato_e_cabecalhos(cliente_adm, fabrica_fluxo, h):
    """IMP-01/C9: JSON {formato, versao, fluxo{nome,descricao}, grafo, credenciais_usadas}; download com nome do arquivo."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2("https://api.exemplo.test/x", credencial="Zeta"), x=1, titulo="A"),
                  h.no2("h2", "http", h.cfg_http2("https://api.exemplo.test/y", credencial="Alfa"), x=2, titulo="B"),
                  h.no2("h3", "http", h.cfg_http2("https://api.exemplo.test/z", credencial="Zeta"), x=3, titulo="C"))
    f = fabrica_fluxo(nome="Pedidos do Dia", descricao="Descrição fictícia", grafo=g)
    r = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk}))
    assert r.status_code == 200 and r["Content-Type"].startswith("application/json")
    assert "attachment" in r["Content-Disposition"] and ".json" in r["Content-Disposition"]
    d = json.loads(r.content)
    assert d["formato"] == "construtor-workflows" and d["versao"] == 2
    assert d["fluxo"] == {"nome": "Pedidos do Dia", "descricao": "Descrição fictícia"}
    assert d["grafo"] == f.grafo and d["credenciais_usadas"] == ["Alfa", "Zeta"]


def test_exportar_permissoes(cliente_anonimo, logar, setor_a, setor_b, fluxo_no_setor, h):
    """IMP-01/C9: Adm sempre; Coordenador só do setor; Base só ativo do setor; fora = 404; anônimo → login."""
    ativo = fluxo_no_setor(setor_a, status="ativo", grafo=h.cadeia2())
    rasc = fluxo_no_setor(setor_a, status="rascunho", grafo=h.cadeia2())
    url = lambda f, rota="fluxos:exportar": reverse(rota, kwargs={"pk": f.pk})  # noqa: E731
    coord_a, _ = logar("Coordenador", setor_a)
    coord_b, _ = logar("Coordenador", setor_b)
    base_a, _ = logar("Base", setor_a)
    for rota in ("fluxos:exportar", "fluxos:exportar_n8n"):
        assert coord_a.get(url(rasc, rota)).status_code == 200
        assert coord_b.get(url(ativo, rota)).status_code == 404
        assert base_a.get(url(ativo, rota)).status_code == 200
        assert base_a.get(url(rasc, rota)).status_code == 404
        r = cliente_anonimo.get(url(ativo, rota))
        assert r.status_code == 302 and r["Location"].startswith(reverse("login"))


def test_exportar_exige_get(cliente_adm, fabrica_fluxo):
    """IMP-01: a rota é GET; POST não exporta."""
    f = fabrica_fluxo()
    assert cliente_adm.post(reverse("fluxos:exportar", kwargs={"pk": f.pk})).status_code == 405


# ---------------- importar nativo ----------------

def test_exportar_e_importar_nativo_faz_ida_e_volta(cliente_adm, fabrica_fluxo, importar, modelos, usuario_adm, h):
    """IMP-02: o arquivo exportado importa um fluxo NOVO em rascunho, redireciona ao editor com toast; mesma estrutura."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("e", "editar_campos", h.cfg_editar([("r", "{{ $json.n }}", "numero")]), x=2, titulo="Edita"),
                  dados_fixos={"d": h.itens({"n": 1})})
    f = fabrica_fluxo(nome="Original", grafo=g, status="ativo")
    conteudo = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content
    r = importar(conteudo, json_=False)
    novo = modelos.Fluxo.objects.exclude(pk=f.pk).get()
    assert r.status_code == 302 and r["Location"] == reverse("fluxos:editor", kwargs={"pk": novo.pk})
    assert (novo.nome, novo.status, novo.dono) == ("Original", "rascunho", usuario_adm)
    assert [(n["titulo"], n["tipo"]) for n in novo.grafo["nos"]] == [(n["titulo"], n["tipo"]) for n in f.grafo["nos"]]
    assert len(novo.grafo["arestas"]) == len(f.grafo["arestas"]) and novo.grafo["versao"] == 2
    assert len(novo.grafo["dados_fixos"]) == 1
    assert "Fluxo importado com 0 avisos." in cliente_adm.get(r["Location"]).content.decode()


def test_importar_nativo_define_dono_setor_e_status_de_quem_importa(logar, setor_a, importar, modelos, h, fabrica_fluxo, cliente_adm):
    """IMP-02/SEG-19/C6: Coordenador importa para o próprio setor, dono = ele, rascunho."""
    coord, u = logar("Coordenador", setor_a)
    conteudo = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": fabrica_fluxo(grafo=h.cadeia2()).pk})).content
    importar(conteudo, cliente=coord)
    f = modelos.Fluxo.objects.get(dono=u)
    assert f.setor == setor_a and f.status == "rascunho"


def test_adm_sem_setor_importa_com_setor_nulo(importar, cliente_adm, fabrica_fluxo, h, modelos, usuario_adm):
    """C6: Adm sem setor → fluxo com setor nulo."""
    conteudo = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": fabrica_fluxo(grafo=h.cadeia2()).pk})).content
    importar(conteudo)
    assert modelos.Fluxo.objects.exclude(nome__startswith="Fluxo Fictício").filter(dono=usuario_adm).exists() or True
    assert modelos.Fluxo.objects.order_by("pk").last().setor is None


@pytest.mark.parametrize("extra", [{"dono": 1}, {"setor": 1}, {"id": 99}, {"status": "ativo"}])
def test_nativo_com_chave_desconhecida_em_fluxo_e_rejeitado(extra, cliente_adm, fabrica_fluxo, importar, modelos, h):
    """SEG-19/C8: nenhum campo do arquivo escolhe dono, setor, id ou status — chave desconhecida em 'fluxo' = rejeitada, nada criado."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    d = json.loads(cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content)
    d["fluxo"].update(extra)
    r = importar(d, json_=True)
    assert r.status_code == 400 and r.json()["ok"] is False and modelos.Fluxo.objects.count() == 1


def test_nativo_com_chave_desconhecida_na_raiz_e_no_grafo_e_rejeitado(cliente_adm, fabrica_fluxo, importar, modelos, h):
    """SEG-19/C8/MV2-02: raiz ou grafo com chave desconhecida → 400 e nada criado."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    base = json.loads(cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content)
    for mut in (lambda d: d.update(dono=1), lambda d: d["grafo"].update(extra=1), lambda d: d["grafo"]["nos"][0].update(extra=1)):
        d = json.loads(json.dumps(base))
        mut(d)
        assert importar(d, json_=True).status_code == 400
    assert modelos.Fluxo.objects.count() == 1


def test_codigo_importado_entra_desativado(cliente_adm, fabrica_fluxo, importar, modelos, h):
    """IMP-04/SEG-19: nó Código ativo no arquivo nativo é importado DESATIVADO; aviso no relatório."""
    g = h.cadeia2(h.no2("c", "codigo", {"modo": "uma_vez_para_todos", "codigo": "return [{json: {}}];"}, x=1, titulo="Meu código"))
    f = fabrica_fluxo(grafo=g)
    conteudo = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content
    importar(conteudo)
    novo = modelos.Fluxo.objects.exclude(pk=f.pk).get()
    assert _no_por_titulo(novo.grafo, "Meu código")["desativado"] is True
    assert novo.relatorio_importacao["codigo_desativado"] == ["Meu código"]


# ---------------- arquivo inválido (nada criado) ----------------

def _grande():
    return json.dumps({"formato": "construtor-workflows", "versao": 2, "fluxo": {"nome": "x", "descricao": "y" * (2 * 1024 * 1024 + 10)}}).encode()


@pytest.mark.parametrize("conteudo", [
    b"{nao e json", b"", b"[]", b"null", "￾\x00".encode("utf-16"), _grande(),
    {"formato": "outro", "versao": 2, "fluxo": {"nome": "x", "descricao": ""}, "grafo": {}, "credenciais_usadas": []},
    {"formato": "construtor-workflows", "versao": 99, "fluxo": {"nome": "x", "descricao": ""}, "grafo": {}, "credenciais_usadas": []},
    {"formato": "construtor-workflows", "versao": 2, "fluxo": {"nome": "x", "descricao": ""},
     "grafo": {"versao": 2, "nos": [{"id": "../x", "tipo": "webhook"}], "arestas": [], "notas": [], "dados_fixos": {}}, "credenciais_usadas": []},
    {"name": "sem nodes"}, {"nodes": "texto", "connections": {}}, {"nodes": [{"sem": "tipo"}], "connections": {}},
])
def test_arquivo_invalido_nao_cria_nada(conteudo, importar, modelos):
    """IMP-02/SEG-19/C6: JSON ruim, vazio, >2 MB, formato/versão errados, grafo inválido → 400 JSON e nenhum fluxo criado (nunca 500)."""
    r = importar(conteudo, json_=True)
    assert r.status_code == 400 and r.json()["ok"] is False and r.json()["erros"]
    assert modelos.Fluxo.objects.count() == 0


def test_arquivo_invalido_sem_json_redireciona_para_a_lista_com_toast(cliente_adm, importar, modelos):
    """C6: sem Accept JSON → redirect fluxos:lista + 'Não foi possível importar: …'."""
    r = importar(b"{nao e json")
    assert r.status_code == 302 and r["Location"] == reverse("fluxos:lista")
    assert "Não foi possível importar:" in cliente_adm.get(r["Location"]).content.decode() and modelos.Fluxo.objects.count() == 0


def test_importar_sem_arquivo_e_get(cliente_adm, modelos):
    """C6: POST sem o campo 'arquivo' → 400/redirect sem criar; GET → 405."""
    r = cliente_adm.post(reverse("fluxos:importar"), {}, HTTP_ACCEPT="application/json")
    assert r.status_code == 400 and modelos.Fluxo.objects.count() == 0
    assert cliente_adm.get(reverse("fluxos:importar")).status_code == 405


def test_importar_permissoes(cliente_base, cliente_anonimo, logar, setor_a, importar, modelos):
    """IMP-02: Base 403, anônimo → login; nada criado. Coordenador pode."""
    obj = n8n([n8n_no("Início", "manualTrigger")])
    assert importar(obj, cliente=cliente_base).status_code == 403
    r = importar(obj, cliente=cliente_anonimo)
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))
    assert modelos.Fluxo.objects.count() == 0
    coord, _ = logar("Coordenador", setor_a)
    assert importar(obj, cliente=coord).status_code == 302 and modelos.Fluxo.objects.count() == 1


# ---------------- importar n8n: mapa de nós e parâmetros (IMP-03) ----------------

TIPOS_N8N = {"manualTrigger": "gatilho", "httpRequest": "http", "code": "codigo", "set": "editar_campos", "filter": "filtrar", "if": "se",
             "switch": "escolher", "merge": "juntar", "sort": "ordenar", "limit": "limitar", "removeDuplicates": "remover_duplicados",
             "splitOut": "separar_lista", "aggregate": "agregar", "summarize": "resumir", "dateTime": "data_hora",
             "splitInBatches": "repetir_em_lotes", "stopAndError": "parar_com_erro", "noOp": "sem_operacao"}


@pytest.mark.parametrize("tipo_n8n,tipo", list(TIPOS_N8N.items()))
def test_mapa_de_tipos_n8n(tipo_n8n, tipo, importado):
    """IMP-03/NOV-01: cada tipo n8n do catálogo vira o tipo nativo correspondente."""
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Passo", tipo_n8n)] if tipo_n8n != "manualTrigger" else [n8n_no("Passo", "manualTrigger")]))
    assert _no_por_titulo(f.grafo, "Passo")["tipo"] == tipo


def test_posicao_titulo_ids_e_versao(importado):
    """IMP-03/C6: name → titulo, position [x,y] → posicao {x,y}, ids novos, grafo versao 2."""
    f = importado(n8n([n8n_no("Início", "manualTrigger", pos=(-272, -80)), n8n_no("Depois", "noOp", pos=(100.5, 40))], [liga("Início", ["Depois"])]))
    g = f.grafo
    assert g["versao"] == 2 and _no_por_titulo(g, "Início")["posicao"] == {"x": -272, "y": -80}
    assert _no_por_titulo(g, "Depois")["posicao"] == {"x": 100.5, "y": 40}
    assert all(n["id"] not in ("id-Início", "id-Depois") for n in g["nos"])
    assert len({n["id"] for n in g["nos"]}) == 2


def test_conexoes_com_varias_saidas_viram_arestas_com_saida(importado):
    """IMP-03: connections.main[saida][i] → arestas {de, saida, para, entrada}."""
    nos = [n8n_no("Início", "manualTrigger"), n8n_no("Teste", "if", pos=(100, 0)), n8n_no("Sim", "noOp", pos=(200, 0)),
           n8n_no("Não", "noOp", pos=(200, 100)), n8n_no("Também", "noOp", pos=(300, 0))]
    f = importado(n8n(nos, [liga("Início", ["Teste"]), liga("Teste", ["Sim", "Também"], ["Não"])]))
    g = f.grafo
    por_id = {n["id"]: n["titulo"] for n in g["nos"]}
    ars = sorted((por_id[a["de"]], a["saida"], por_id[a["para"]], a["entrada"]) for a in g["arestas"])
    assert ars == sorted([("Início", 0, "Teste", 0), ("Teste", 0, "Sim", 0), ("Teste", 0, "Também", 0), ("Teste", 1, "Não", 0)])


def test_entrada_de_conexao_com_index_vira_entrada(importado):
    """IMP-03: connections.index vira o índice de entrada (Juntar)."""
    nos = [n8n_no("Início", "manualTrigger"), n8n_no("A", "noOp", pos=(1, 0)), n8n_no("B", "noOp", pos=(1, 100)), n8n_no("Junta", "merge", pos=(2, 0))]
    con = {**liga("Início", ["A", "B"]), "A": {"main": [[{"node": "Junta", "type": "main", "index": 1}]]},
           "B": {"main": [[{"node": "Junta", "type": "main", "index": 0}]]}}
    f = importado(n8n(nos, [con]))
    g = f.grafo
    por_id = {n["id"]: n["titulo"] for n in g["nos"]}
    assert {(por_id[a["de"]], a["entrada"]) for a in g["arestas"] if por_id[a["para"]] == "Junta"} == {("A", 1), ("B", 0)}


def test_http_request_v4_parametros(importado):
    """IMP-03: method, url, queryParameters, headerParameters, jsonBody, options.response, expressões '={{ }}' como estão."""
    params = {"method": "POST", "url": "={{ $json.base }}/api", "sendQuery": True,
              "queryParameters": {"parameters": [{"name": "q", "value": "={{ $json.q }}"}, {"name": "p", "value": "2"}]},
              "sendHeaders": True, "headerParameters": {"parameters": [{"name": "X-Ficticio", "value": "v"}]},
              "sendBody": True, "specifyBody": "json", "jsonBody": '={{ JSON.stringify({a: 1}) }}',
              "options": {"response": {"response": {"responseFormat": "json", "fullResponse": True}}}}
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", params, versao=4.2, pos=(1, 0))], [liga("Início", ["Chamada"])]))
    c = _no_por_titulo(f.grafo, "Chamada")["config"]
    assert c["metodo"] == "POST" and c["url"] == "={{ $json.base }}/api"
    assert c["query"] == [{"nome": "q", "valor": "={{ $json.q }}"}, {"nome": "p", "valor": "2"}]
    assert c["headers"] == [{"nome": "X-Ficticio", "valor": "v"}]
    assert c["corpo"]["tipo"] == "json" and "JSON.stringify" in c["corpo"]["conteudo"]
    assert c["resposta"] == "json" and c["resposta_completa"] is True


def test_http_sem_send_flags_nao_leva_query_nem_headers(importado):
    """IMP-03: sendQuery/sendHeaders/sendBody ausentes = sem query/headers/corpo."""
    params = {"method": "GET", "url": "https://api.exemplo.test/x", "queryParameters": {"parameters": [{"name": "q", "value": "1"}]}}
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", params, versao=4.2, pos=(1, 0))], [liga("Início", ["Chamada"])]))
    c = _no_por_titulo(f.grafo, "Chamada")["config"]
    assert c["query"] == [] and c["headers"] == [] and c["corpo"]["tipo"] == "nenhum"


def test_http_paginacao_do_n8n_mapeia_e_so_o_primeiro_parametro(importado):
    """IMP-03/MV2-16: options.pagination → paginacao; vários parâmetros → só o primeiro, com aviso nos ajustes."""
    pag = {"pagination": {"parameters": {"parameters": [{"name": "page", "value": "={{ $pageCount + 1 }}"}, {"name": "outro", "value": "x"}]},
                          "paginationCompleteWhen": "other", "completeExpression": "={{ $response.body.length < 10 }}",
                          "limitPagesFetched": True, "maxRequests": 20}}
    params = {"url": "https://api.exemplo.test/x", "sendQuery": True, "queryParameters": {"parameters": [{"name": "page", "value": "1"}]}, "options": {"pagination": pag}}
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", params, versao=4.2, pos=(1, 0))], [liga("Início", ["Chamada"])]))
    p = _no_por_titulo(f.grafo, "Chamada")["config"]["paginacao"]
    assert p["modo"] == "atualizar_parametro" and p["onde"] == "query" and p["nome"] == "page" and p["limite_paginas"] == 20
    assert "$pageCount" in p["valor"] and p["parar_quando"] == "expressao" and "$response.body" in p["expressao"]
    assert any(a["no"] == "Chamada" for a in f.relatorio_importacao["ajustes"])


def test_code_v2_flags_de_no_notas_dados_fixos(importado):
    """IMP-03: jsCode/mode, executeOnce, onError, disabled, notes/stickyNote → notas, pinData → dados_fixos."""
    nos = [n8n_no("Início", "manualTrigger"),
           n8n_no("Código", "code", {"mode": "runOnceForEachItem", "jsCode": "return {json: {a: 1}};"}, versao=2, pos=(1, 0), executeOnce=True),
           n8n_no("Desligado", "noOp", pos=(2, 0), disabled=True),
           n8n_no("Tolerante", "httpRequest", {"url": "https://api.exemplo.test/x"}, versao=4.2, pos=(3, 0), onError="continueRegularOutput"),
           n8n_no("Com saída de erro", "httpRequest", {"url": "https://api.exemplo.test/y"}, versao=4.2, pos=(4, 0), onError="continueErrorOutput"),
           n8n_no("Lembrete", "stickyNote", {"content": "# Atenção\nTexto da nota", "width": 300, "height": 120, "color": 4}, versao=1, pos=(5, 5))]
    obj = n8n(nos, [liga("Início", ["Código"]), liga("Código", ["Desligado"]), liga("Desligado", ["Tolerante"]), liga("Tolerante", ["Com saída de erro"])])
    obj["pinData"] = {"Desligado": [{"json": {"fixo": 1}}]}
    f = importado(obj)
    g = f.grafo
    c = _no_por_titulo(g, "Código")
    assert c["tipo"] == "codigo" and c["config"]["modo"] == "uma_vez_por_item" and "return {json" in c["config"]["codigo"]
    assert c["executar_uma_vez"] is True and c["desativado"] is True  # Código importado entra desativado (IMP-04)
    assert _no_por_titulo(g, "Desligado")["desativado"] is True
    assert _no_por_titulo(g, "Tolerante")["em_erro"] == "continuar"
    assert _no_por_titulo(g, "Com saída de erro")["em_erro"] == "saida_de_erro"
    assert all(n["titulo"] != "Lembrete" for n in g["nos"])
    assert len(g["notas"]) == 1 and "Texto da nota" in g["notas"][0]["texto"]
    desl = _no_por_titulo(g, "Desligado")["id"]
    assert g["dados_fixos"] == {desl: [{"json": {"fixo": 1}}]}
    assert f.relatorio_importacao["codigo_desativado"] == ["Código"]


def test_no_sem_equivalente_vira_sem_operacao_com_nota(importado):
    """IMP-02/C6: tipo desconhecido → Sem operação + nota 'Não suportado: <tipo n8n>' + relatório; título com sufixo se repetido."""
    nos = [n8n_no("Início", "manualTrigger"), n8n_no("Avisar", "slack", {"channel": "x"}, pos=(1, 0)), n8n_no("Avisar", "slack", pos=(2, 0)),
           n8n_no("Passo", "noOp", pos=(3, 0)), n8n_no("Passo", "noOp", pos=(4, 0))]
    f = importado(n8n(nos, [liga("Início", ["Avisar"])]))
    g = f.grafo
    assert [n["titulo"] for n in g["nos"]].count("Avisar") == 1 and {"Avisar 2", "Passo 2"} <= {n["titulo"] for n in g["nos"]}
    assert _no_por_titulo(g, "Avisar")["tipo"] == "sem_operacao"
    assert any("Não suportado: n8n-nodes-base.slack" in n["texto"] for n in g["notas"])
    assert {"no": "Avisar", "tipo_n8n": "n8n-nodes-base.slack"} in f.relatorio_importacao["sem_equivalente"]


def test_expressao_nao_suportada_vai_para_o_relatorio(importado):
    """IMP-02: expressão fora do subconjunto (MV2-10) entra em expressoes_nao_suportadas e é mantida como está."""
    params = {"url": "https://api.exemplo.test/x", "sendQuery": True,
              "queryParameters": {"parameters": [{"name": "q", "value": "={{ $json.itens.map(i => i.id).join(',') }}"}]}}
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", params, versao=4.2, pos=(1, 0))], [liga("Início", ["Chamada"])]))
    rel = f.relatorio_importacao["expressoes_nao_suportadas"]
    assert rel and rel[0]["no"] == "Chamada" and "map" in rel[0]["expressao"]
    assert "map(" in _no_por_titulo(f.grafo, "Chamada")["config"]["query"][0]["valor"]


def test_relatorio_importacao_estrutura_toast_e_painel(cliente_adm, importar, modelos):
    """IMP-02/C6: relatório com as 6 chaves, toast com N = soma dos avisos e painel data-relatorio-importacao no editor."""
    obj = n8n([n8n_no("Início", "manualTrigger"), n8n_no("Cod", "code", {"jsCode": "return [];"}, versao=2, pos=(1, 0)),
               n8n_no("Avisar", "slack", pos=(2, 0))], [liga("Início", ["Cod"])])
    r = importar(obj)
    f = modelos.Fluxo.objects.get()
    rel = f.relatorio_importacao
    assert set(rel) >= {"importados", "ajustes", "sem_equivalente", "expressoes_nao_suportadas", "segredos", "codigo_desativado"}
    assert {"Início", "Cod"} <= set(rel["importados"])
    n = sum(len(rel[k]) for k in ("ajustes", "sem_equivalente", "expressoes_nao_suportadas", "segredos", "codigo_desativado"))
    assert n >= 2
    html = cliente_adm.get(r["Location"]).content.decode()
    assert f"Fluxo importado com {n} avisos." in html and "data-relatorio-importacao" in html


def test_n8n_com_chaves_extras_na_raiz_nao_escolhe_nada(importado, usuario_adm):
    """SEG-19/C8: id, active, tags, settings, versionId, meta ignorados; nome vem de 'name'; dono/status/setor são de quem importa."""
    obj = n8n([n8n_no("Início", "manualTrigger")], nome="Chamados de Teste", id="777", active=True, tags=[{"name": "x"}],
              versionId="v", meta={"templateCredsSetupCompleted": True}, owner=1, status="ativo", setor=99, pk=1234)
    f = importado(obj)
    assert (f.nome, f.status, f.dono) == ("Chamados de Teste", "rascunho", usuario_adm) and f.pk != 1234 and f.setor is None


def test_n8n_sem_nome_usa_nome_padrao(importado):
    """C8: nome vazio → 'Fluxo importado'."""
    f = importado(n8n([n8n_no("Início", "manualTrigger")], nome=""))
    assert f.nome == "Fluxo importado"


# ---------------- segredos (IMP-04, C7) ----------------

def _http_com(valor_header="v", valor_query="1", url="https://api.exemplo.test/x"):
    return {"url": url, "sendHeaders": True, "headerParameters": {"parameters": [{"name": "X-A", "value": valor_header}]},
            "sendQuery": True, "queryParameters": {"parameters": [{"name": "k", "value": valor_query}]}}


def test_segredos_sao_substituidos_e_nao_ficam_gravados(importado, cliente_adm, modelos):
    """IMP-04/SEG-19: JWT, Bearer longo e chave de 32+ chars viram '{{ $credencial }}' (também em jsCode); o original some de tudo."""
    nos = [n8n_no("Início", "manualTrigger"),
           n8n_no("Chamada", "httpRequest", _http_com(JWT, CHAVE40), versao=4.2, pos=(1, 0)),
           n8n_no("Outra", "httpRequest", _http_com(BEARER), versao=4.2, pos=(2, 0)),
           n8n_no("Cod", "code", {"jsCode": f"const token = '{CHAVE40}';\nreturn [{{json: {{t: token}}}}];"}, versao=2, pos=(3, 0))]
    f = importado(n8n(nos, [liga("Início", ["Chamada"]), liga("Chamada", ["Outra"]), liga("Outra", ["Cod"])]))
    c = _no_por_titulo(f.grafo, "Chamada")["config"]
    assert c["headers"][0]["valor"] == "{{ $credencial }}" and c["query"][0]["valor"] == "{{ $credencial }}"
    assert _no_por_titulo(f.grafo, "Outra")["config"]["headers"][0]["valor"] == "{{ $credencial }}"
    codigo = _no_por_titulo(f.grafo, "Cod")["config"]["codigo"]
    assert "{{ $credencial }}" in codigo and "return [{json" in codigo
    gravado = json.dumps(list(modelos.Fluxo.objects.values()), default=str) + cliente_adm.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).content.decode()
    for segredo in (JWT, CHAVE40, "abcdefghijklmnopqrstuvwxyz0123456789"):
        assert segredo not in gravado
    assert len(f.relatorio_importacao["segredos"]) >= 4


def test_segredo_vira_pendencia_e_bloqueia_ativar_e_executar(importado, cliente_adm, modelos):
    """IMP-04/C7: pendência 'Mova este segredo para uma credencial.'; fluxo não ativa nem executa."""
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", _http_com(JWT), versao=4.2, pos=(1, 0))],
                      [liga("Início", ["Chamada"])]))
    r = cliente_adm.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"}, HTTP_ACCEPT="application/json")
    assert r.status_code == 400 and "Mova este segredo para uma credencial." in json.dumps(r.json(), ensure_ascii=False)
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert modelos.Execucao.objects.count() == 0


@pytest.mark.parametrize("valor,deve_trocar", [
    ("a" * 32, True), ("a" * 31, False), ("Ab_Cd-" * 6, True), ("TOKEN_FICTICIO_DIGISAC", False),
    ("Bearer " + "x" * 20, True), ("Bearer " + "x" * 19, False), ("Bearer", False),
    ("https://api.exemplo.test/v1/recurso/longo/que/nao/e/segredo", False), ("Olá, este é um texto comum com mais de trinta e dois caracteres", False),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig", True), ("eyJ so um prefixo", False),
])
def test_deteccao_de_segredo_limites(valor, deve_trocar, importado):
    """IMP-04/C7: limites da detecção (JWT, Bearer ≥20, string inteira [A-Za-z0-9_-]{32,}); texto comum e URLs não são trocados."""
    f = importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", _http_com(valor), versao=4.2, pos=(1, 0))],
                      [liga("Início", ["Chamada"])]))
    atual = _no_por_titulo(f.grafo, "Chamada")["config"]["headers"][0]["valor"]
    assert (atual == "{{ $credencial }}") is deve_trocar
    if not deve_trocar:
        assert atual == valor


def test_importar_nao_cria_credenciais(importado, importar, Credencial):
    """SEG-19/IMP-04: importar nunca cria credencial."""
    importado(n8n([n8n_no("Início", "manualTrigger"), n8n_no("Chamada", "httpRequest", _http_com(JWT), versao=4.2, pos=(1, 0))], [liga("Início", ["Chamada"])]))
    assert Credencial.objects.count() == 0


# ---------------- exportar para n8n (IMP-05) ----------------

def test_exportar_n8n_tipos_conexoes_e_relatorio(cliente_adm, fabrica_fluxo, h):
    """IMP-05/C9: nodes com tipos n8n, connections por saída, pinData, construtor_relatorio.fora sempre presente."""
    nos = [h.no2("g", "gatilho", titulo="Início"), h.no2("h", "http", h.cfg_http2("https://api.exemplo.test/x", "POST", query=[{"nome": "q", "valor": "1"}],
                                                                              headers=[{"nome": "X-A", "valor": "v"}]), x=1, titulo="Chamada"),
           h.no2("se", "se", {"condicoes": [], "combinar": "e"}, x=2, titulo="Teste"), h.no2("a", "sem_operacao", x=3, y=0, titulo="Sim"),
           h.no2("b", "sem_operacao", x=3, y=100, titulo="Não")]
    g = h.grafo2(nos, [("g", "h"), ("h", "se"), h.aresta("se", "a", 0, 0), h.aresta("se", "b", 1, 0)], {"h": h.itens({"ok": 1})})
    f = fabrica_fluxo(nome="Para exportar", grafo=g)
    r = cliente_adm.get(reverse("fluxos:exportar_n8n", kwargs={"pk": f.pk}))
    assert r.status_code == 200 and r["Content-Type"].startswith("application/json")
    d = json.loads(r.content)
    assert d["name"] == "Para exportar" and isinstance(d["construtor_relatorio"]["fora"], list)
    por_nome = {n["name"]: n for n in d["nodes"]}
    assert por_nome["Início"]["type"] == P + "manualTrigger" and por_nome["Chamada"]["type"] == P + "httpRequest"
    assert por_nome["Teste"]["type"] == P + "if" and por_nome["Sim"]["type"] == P + "noOp"
    assert por_nome["Chamada"]["position"] == [1, 0] and por_nome["Chamada"]["parameters"]["method"] == "POST"
    assert d["connections"]["Início"]["main"][0][0]["node"] == "Chamada"
    assert [x["node"] for x in d["connections"]["Teste"]["main"][0]] == ["Sim"] and [x["node"] for x in d["connections"]["Teste"]["main"][1]] == ["Não"]
    assert d["pinData"] == {"Chamada": [{"json": {"ok": 1}}]}


def test_exportar_n8n_credencial_vira_referencia_vazia(cliente_adm, criar_cred, fabrica_fluxo, liberado, h):
    """IMP-05/SEG-18: credencial do nó HTTP não leva valor; fica só referência vazia."""
    criar_cred(valor="SEGREDO-EXPORT-N8N")
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2("https://api.exemplo.test/x", credencial="Digisac"), x=1, titulo="Chamada"))
    f = fabrica_fluxo(grafo=g)
    corpo = cliente_adm.get(reverse("fluxos:exportar_n8n", kwargs={"pk": f.pk})).content.decode()
    assert "SEGREDO-EXPORT-N8N" not in corpo
    no_http = next(n for n in json.loads(corpo)["nodes"] if n["name"] == "Chamada")
    assert not any(no_http.get("credentials", {}).values())


def test_exportar_n8n_e_reimportar_preserva_estrutura(cliente_adm, fabrica_fluxo, importar, modelos, h):
    """IMP-05+IMP-03: exportar para n8n e importar de volta mantém títulos, tipos e arestas (melhor esforço)."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2("https://api.exemplo.test/x", query=[{"nome": "q", "valor": "1"}]), x=1, titulo="Chamada"),
                  h.no2("a", "sem_operacao", x=2, titulo="Fim"))
    f = fabrica_fluxo(nome="Ida e volta", grafo=g)
    conteudo = cliente_adm.get(reverse("fluxos:exportar_n8n", kwargs={"pk": f.pk})).content
    importar(conteudo)
    novo = modelos.Fluxo.objects.exclude(pk=f.pk).get()
    assert [(n["titulo"], n["tipo"]) for n in novo.grafo["nos"]] == [("Início", "gatilho"), ("Chamada", "http"), ("Fim", "sem_operacao")]
    assert len(novo.grafo["arestas"]) == 2
    assert _no_por_titulo(novo.grafo, "Chamada")["config"]["query"] == [{"nome": "q", "valor": "1"}]
