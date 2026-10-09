"""Aceite M5 parte B: HTTP v2 (NOV-05) e paginação (MV2-16). Servidor 100% local; SEG-01..10 continuam valendo."""

import json
import time

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]


def _jsons(n):
    return [i["json"] for i in n.saida]


# ---------------- respostas → itens ----------------

def test_resposta_lista_vira_um_item_por_elemento(http_no, liberado, h):
    """NOV-05/MV2-12 L1: corpo lista → 1 item por elemento (json = elemento)."""
    e, n = http_no(h.cfg_http2(f"{liberado.base}/lista"))
    assert e.status == "sucesso" and _jsons(n) == [{"id": 1}, {"id": 2}, {"id": 3}] and n.itens_saida == 3


def test_resposta_objeto_vira_um_item_com_o_corpo(http_no, liberado, h):
    """NOV-05/MV2-12 L1: corpo objeto → 1 item, json = corpo."""
    e, n = http_no(h.cfg_http2(f"{liberado.base}/ok"))
    assert _jsons(n) == [{"ok": True, "n": 1}]


def test_resposta_completa_traz_status_headers_e_corpo(http_no, liberado, h):
    """MV2-12 L1: resposta_completa=true → json = {status, headers (minúsculos), corpo}."""
    e, n = http_no(h.cfg_http2(f"{liberado.base}/ok", resposta_completa=True))
    j = _jsons(n)[0]
    assert j["status"] == 200 and j["corpo"] == {"ok": True, "n": 1}
    assert all(k == k.lower() for k in j["headers"]) and "content-type" in j["headers"]


def test_resposta_texto_e_data(http_no, liberado, h):
    """NOV-05/MV2-15 B6: resposta=texto → item {data: texto}."""
    liberado.rotas["/txt"] = lambda req: (200, b"ola, texto cru", {"Content-Type": "text/plain"})
    e, n = http_no(h.cfg_http2(f"{liberado.base}/txt", resposta="texto"))
    assert _jsons(n) == [{"data": "ola, texto cru"}]


def test_resposta_json_com_corpo_invalido_e_json_invalido(http_no, liberado, h):
    """NOV-05/B6: resposta=json com corpo que não é JSON → erro json_invalido."""
    liberado.rotas["/txt"] = lambda req: (200, b"isto nao e json", {"Content-Type": "text/plain"})
    e, n = http_no(h.cfg_http2(f"{liberado.base}/txt", resposta="json"))
    assert e.status == "erro" and n.erro_categoria == "json_invalido"


def test_resposta_automatica_decide_pelo_content_type(http_no, liberado, h):
    """NOV-05/B6: automatica → JSON se application/json, senão texto."""
    liberado.rotas["/txt"] = lambda req: (200, b"so texto", {"Content-Type": "text/plain"})
    _, n = http_no(h.cfg_http2(f"{liberado.base}/txt", resposta="automatica"))
    assert _jsons(n) == [{"data": "so texto"}]
    _, n = http_no(h.cfg_http2(f"{liberado.base}/ok", resposta="automatica"))
    assert _jsons(n) == [{"ok": True, "n": 1}]


def test_resposta_lista_vazia_gera_zero_itens_e_o_proximo_fica_sem_itens(executar, cliente_adm, liberado, h, no):
    """NOV-05/MV2-01: corpo [] → 0 itens; o nó seguinte vira sem_itens."""
    liberado.rotas["/vazia"] = lambda req: (200, [], None)
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/vazia"), x=1), h.no2("f", "sem_operacao", x=2))
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and no(e, "h").itens_saida == 0 and no(e, "f").status == "sem_itens"


# ---------------- expressões na config, por item ----------------

def test_url_query_headers_e_corpo_resolvem_expressoes_por_item(http_no, liberado, h):
    """NOV-05/MV2-10: cada item gera a sua requisição com url/query/header/corpo resolvidos."""
    cfg = h.cfg_http2(f"{liberado.base}/eco/{{{{ $json.id }}}}", "POST",
                      query=[{"nome": "q", "valor": "{{ $json.nome }}"}],
                      headers=[{"nome": "X-Item", "valor": "={{ 'i' + $json.id }}"}],
                      corpo={"tipo": "json", "conteudo": '{"id": {{ $json.id }}, "nome": "{{ $json.nome }}"}'})
    e, n = http_no(cfg, [{"id": 1, "nome": "Ana"}, {"id": 2, "nome": "Bia"}])
    assert e.status == "sucesso"
    hits = liberado.hits("/eco/")
    assert [r["rota"] for r in hits] == ["/eco/1", "/eco/2"]
    assert hits[1]["query"] == {"q": ["Bia"]} and hits[1]["headers"]["x-item"] == "i2"
    assert json.loads(hits[0]["corpo"]) == {"id": 1, "nome": "Ana"}
    assert hits[0]["headers"]["content-type"].startswith("application/json")


def test_insercao_segura_na_url_e_no_corpo_json(http_no, liberado, h):
    """NOV-05/PLH-04: valor com / ? # @ é percent-encoded na URL; aspas no corpo JSON são escapadas."""
    cfg = h.cfg_http2(f"{liberado.base}/eco/{{{{ $json.v }}}}", "POST",
                      corpo={"tipo": "json", "conteudo": '{"v": "{{ $json.v }}"}'})
    e, _ = http_no(cfg, [{"v": 'a/b?c#d@e"f'}])
    assert e.status == "sucesso"
    r = liberado.hits("/eco/")[0]
    assert r["rota"].count("/") == 2 and "?" not in r["path"] and "#" not in r["path"]
    assert json.loads(r["corpo"]) == {"v": 'a/b?c#d@e"f'}


def test_corpo_formulario_e_texto(http_no, liberado, h):
    """NOV-05/B6: formulario → x-www-form-urlencoded; texto → corpo cru."""
    cfg = h.cfg_http2(f"{liberado.base}/eco", "POST",
                      corpo={"tipo": "formulario", "conteudo": [{"nome": "a", "valor": "1 2"}, {"nome": "b", "valor": "{{ $json.x }}"}]})
    http_no(cfg, [{"x": "ç"}])
    r = liberado.hits("/eco")[0]
    assert r["headers"]["content-type"].startswith("application/x-www-form-urlencoded")
    from urllib.parse import parse_qs
    assert parse_qs(r["corpo"]) == {"a": ["1 2"], "b": ["ç"]}
    http_no(h.cfg_http2(f"{liberado.base}/eco", "POST", corpo={"tipo": "texto", "conteudo": "linha {{ $json.x }}"}), [{"x": 9}])
    assert liberado.hits("/eco")[1]["corpo"] == "linha 9"


def test_corpo_nenhum_nao_envia_corpo(http_no, liberado, h):
    """NOV-05/B6: corpo.tipo nenhum → sem corpo."""
    http_no(h.cfg_http2(f"{liberado.base}/eco", "POST"))
    assert liberado.hits("/eco")[0]["corpo"] == ""


def test_crlf_vindo_de_expressao_em_header_e_erro_placeholder(http_no, liberado, h):
    """NOV-05/SEG-16(3): CR/LF resolvido em header recusa a requisição (nada enviado)."""
    cfg = h.cfg_http2(f"{liberado.base}/eco", headers=[{"nome": "X-A", "valor": "{{ $json.v }}"}])
    e, n = http_no(cfg, [{"v": "a\r\nInjetado: 1"}])
    assert e.status == "erro" and n.erro_categoria == "placeholder" and liberado.hits("/eco") == []


def test_erros_seg10_continuam_valendo(http_no, liberado, h):
    """NOV-05/SEG-10: 404 → http_4xx, 500 → http_5xx."""
    assert http_no(h.cfg_http2(f"{liberado.base}/status/404"))[1].erro_categoria == "http_4xx"
    assert http_no(h.cfg_http2(f"{liberado.base}/status/500"))[1].erro_categoria == "http_5xx"


# ---------------- SSRF por requisição (SEG-01..08) ----------------

@pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data/", "http://localhost/x", "http://[::1]/x",
                                 "http://2130706433/x", "http://0177.0.0.1/x", "http://user:pw@127.0.0.1/"])
def test_ssrf_no_http_v2(url, http_no, liberado, h):
    """NOV-05/SEG-01..06: destinos proibidos → bloqueado_ssrf (ou pendência/erro de URL), nada é enviado."""
    e, n = http_no(h.cfg_http2(url))
    assert e.status == "erro" and n.erro_categoria in ("bloqueado_ssrf", "placeholder") and liberado.requisicoes == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://exemplo.test/x", "gopher://exemplo.test/", "javascript:alert(1)", "data:text/plain,x"])
def test_esquema_nao_http_literal_e_pendencia_e_nao_executa(url, cliente_adm, fabrica_fluxo, salvar_grafo, modelos, liberado, h):
    """SEG-01/SEG-16(8)/GRF-04: esquema não-http LITERAL na url = pendência ao salvar; a execução nem inicia (nada enviado)."""
    f = fabrica_fluxo(grafo=h.cadeia2(), status="rascunho")
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(url), x=1))
    r = salvar_grafo(cliente_adm, f, g)
    assert r.status_code == 200 and any(p["no"] == "h" for p in r.json()["pendencias"])
    f.refresh_from_db()
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert modelos.Execucao.objects.count() == 0 and liberado.requisicoes == []


def test_servidor_local_nao_liberado_e_bloqueado(http_no, liberado, nao_liberado, h):
    """SEG-08: só o host:porta liberado passa; outro servidor local é bloqueado."""
    e, n = http_no(h.cfg_http2(f"{nao_liberado.base}/ok"))
    assert n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []


def test_url_vinda_de_expressao_tambem_e_validada(http_no, liberado, h):
    """SEG-02: expressão que resolve para IP interno é bloqueada na execução."""
    e, n = http_no(h.cfg_http2("{{ $json.alvo }}"), [{"alvo": "http://169.254.169.254/"}])
    assert n.erro_categoria == "bloqueado_ssrf"


def test_redirect_para_destino_proibido_e_bloqueado(http_no, liberado, h):
    """SEG-05: redirect do servidor liberado para 169.254.169.254 é revalidado → bloqueado_ssrf."""
    liberado.rotas["/r"] = lambda req: (302, b"", {"Location": "http://169.254.169.254/"})
    e, n = http_no(h.cfg_http2(f"{liberado.base}/r"))
    assert n.erro_categoria == "bloqueado_ssrf"


# ---------------- requisições gravadas (B10) ----------------

def test_requisicoes_gravadas_com_header_sensivel_mascarado(http_no, liberado, h):
    """MV2-15 B10 / SEG-09: ExecucaoNo.requisicoes {metodo,url,headers,query,corpo,status}; Authorization e query token mascarados."""
    cfg = h.cfg_http2(f"{liberado.base}/ok", query=[{"nome": "token", "valor": "SEGREDO-QUERY"}, {"nome": "q", "valor": "1"}],
                      headers=[{"nome": "Authorization", "valor": "Bearer SEGREDO-HEADER"}, {"nome": "X-Livre", "valor": "visivel"}])
    e, n = http_no(cfg)
    assert e.status == "sucesso" and len(n.requisicoes) == 1
    r = n.requisicoes[0]
    assert {"metodo", "url", "headers", "query", "corpo", "status"} <= set(r)
    assert r["metodo"] == "GET" and r["status"] == 200
    hs = {x["nome"].lower(): x["valor"] for x in r["headers"]}
    assert hs["authorization"] == "••••" and hs["x-livre"] == "visivel"
    qs = {x["nome"]: x["valor"] for x in r["query"]}
    assert qs["token"] == "••••" and qs["q"] == "1"
    assert "SEGREDO" not in json.dumps(n.requisicoes) + json.dumps(e.grafo_snapshot)
    assert liberado.hits("/ok")[0]["headers"]["authorization"] == "Bearer SEGREDO-HEADER"  # o envio real é intacto


# ---------------- paginação (MV2-16) ----------------

def pag(**kw):
    base = {"modo": "atualizar_parametro", "onde": "query", "nome": "page", "valor": "{{ $pageCount + 1 }}",
            "parar_quando": "resposta_vazia", "limite_paginas": 10, "intervalo_ms": 0}
    base.update(kw)
    return base


@pytest.fixture
def paginas(liberado):
    """/pagl?page=N → lista de 2 elementos nas páginas 1..3 e [] depois; /pago → objetos {data, mais, proxima}."""
    def num(req):
        if req["query"].get("page"):
            return int(req["query"]["page"][0])
        return int(req["headers"].get("x-page") or 1)

    def lista(req):
        p = num(req)
        return 200, ([{"p": p, "k": 1}, {"p": p, "k": 2}] if p <= 3 else []), None

    def objeto(req):
        p = num(req)
        proxima = f"{liberado.base}/pago?page={p + 1}" if p < 3 else None
        return 200, {"data": [{"p": p}], "pagina": p, "mais": p < 3, "proxima": proxima}, None

    def corpo(req):
        p = json.loads(req["corpo"] or "{}").get("page", 1)
        return 200, ([{"p": p}] if p <= 2 else []), None

    liberado.rotas.update({"/pagl": lista, "/pago": objeto, "/pagc": corpo,
                           "/infinito": lambda req: (200, [{"x": 1}], None)})
    return liberado


def _pages(srv, rota):
    return [int(r["query"]["page"][0]) for r in srv.hits(rota)]


def test_paginacao_atualizar_parametro_ate_resposta_vazia(http_no, paginas, h):
    """MV2-16: 1ª req = config como está (page=1); depois $pageCount+1 → 2, 3, 4; página vazia encerra e não gera item."""
    cfg = h.cfg_http2(f"{paginas.base}/pagl", query=[{"nome": "page", "valor": "1"}], paginacao=pag())
    e, n = http_no(cfg)
    assert e.status == "sucesso", e.erro_resumo
    assert _pages(paginas, "/pagl") == [1, 2, 3, 4]
    assert [(j["p"], j["k"]) for j in _jsons(n)] == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)]
    assert len(n.requisicoes) == 4 and [r["status"] for r in n.requisicoes] == [200] * 4


def test_paginacao_limite_de_paginas_para_sem_erro(http_no, paginas, h):
    """MV2-16: limite_paginas atingido → para sem erro e entrega o coletado."""
    cfg = h.cfg_http2(f"{paginas.base}/pagl", query=[{"nome": "page", "valor": "1"}], paginacao=pag(limite_paginas=2))
    e, n = http_no(cfg)
    assert e.status == "sucesso" and n.status == "sucesso" and _pages(paginas, "/pagl") == [1, 2] and n.itens_saida == 4


def test_paginacao_limite_padrao_e_10(http_no, paginas, h):
    """MV2-16: sem limite_paginas o padrão é 10 (servidor que nunca esvazia)."""
    p = pag()
    del p["limite_paginas"]
    e, n = http_no(h.cfg_http2(f"{paginas.base}/infinito", paginacao=p))
    assert e.status == "sucesso" and len(paginas.hits("/infinito")) == 10 and n.itens_saida == 10


def test_paginacao_parar_por_expressao_inclui_a_pagina_final(http_no, paginas, h):
    """MV2-16: a página que satisfaz parar_quando=expressao ENTRA na saída (objeto → 1 item por página)."""
    cfg = h.cfg_http2(f"{paginas.base}/pago", query=[{"nome": "page", "valor": "1"}],
                      paginacao=pag(parar_quando="expressao", expressao="{{ !$response.body.mais }}"))
    e, n = http_no(cfg)
    assert e.status == "sucesso" and _pages(paginas, "/pago") == [1, 2, 3]
    assert [j["pagina"] for j in _jsons(n)] == [1, 2, 3]


def test_paginacao_parar_por_status_nao_inclui_a_pagina_nem_erra(http_no, paginas, h):
    """MV2-16: parar_quando=status {codigos}: encerra sem erro e a página com esse status não entra."""
    paginas.rotas["/pst"] = lambda req: (404, {"erro": "fim"}, None) if int(req["query"]["page"][0]) >= 3 else (200, {"data": [1], "pg": int(req["query"]["page"][0])}, None)
    cfg = h.cfg_http2(f"{paginas.base}/pst", query=[{"nome": "page", "valor": "1"}], paginacao=pag(parar_quando="status", codigos=[404]))
    e, n = http_no(cfg)
    assert e.status == "sucesso" and n.status == "sucesso"
    assert [j["pg"] for j in _jsons(n)] == [1, 2] and len(paginas.hits("/pst")) == 3


def test_paginacao_proxima_url(http_no, paginas, h):
    """MV2-16: modo proxima_url segue a URL calculada de $response.body; cada página chega ao servidor."""
    cfg = h.cfg_http2(f"{paginas.base}/pago?page=1",
                      paginacao={"modo": "proxima_url", "url": "{{ $response.body.proxima }}", "parar_quando": "expressao",
                                 "expressao": "{{ !$response.body.proxima }}", "limite_paginas": 10, "intervalo_ms": 0})
    e, n = http_no(cfg)
    assert e.status == "sucesso", e.erro_resumo
    assert [r["path"] for r in paginas.hits("/pago")] == ["/pago?page=1", "/pago?page=2", "/pago?page=3"]
    assert [j["pagina"] for j in _jsons(n)] == [1, 2, 3]


def test_paginacao_pelo_header(http_no, paginas, h):
    """MV2-16: onde=header atualiza o header a cada página."""
    cfg = h.cfg_http2(f"{paginas.base}/pagl", headers=[{"nome": "X-Page", "valor": "1"}],
                      paginacao=pag(onde="header", nome="X-Page"))
    e, n = http_no(cfg)
    assert e.status == "sucesso", e.erro_resumo
    assert [r["headers"]["x-page"] for r in paginas.hits("/pagl")] == ["1", "2", "3", "4"]


def test_paginacao_pelo_corpo_json(http_no, paginas, h):
    """MV2-16: onde=corpo (corpo.tipo json, nome = caminho do campo)."""
    cfg = h.cfg_http2(f"{paginas.base}/pagc", "POST", corpo={"tipo": "json", "conteudo": '{"page": 1}'}, paginacao=pag(onde="corpo"))
    e, n = http_no(cfg)
    assert e.status == "sucesso", e.erro_resumo
    assert [json.loads(r["corpo"])["page"] for r in paginas.hits("/pagc")] == [1, 2, 3]
    assert [j["p"] for j in _jsons(n)] == [1, 2]


def test_paginacao_cada_pagina_passa_pelo_ssrf(http_no, paginas, nao_liberado, h):
    """MV2-16/SEG-02: proxima_url apontando para destino proibido → bloqueado_ssrf na página seguinte; nada chega lá."""
    paginas.rotas["/mal"] = lambda req: (200, {"proxima": f"{nao_liberado.base}/x"}, None)
    cfg = h.cfg_http2(f"{paginas.base}/mal", paginacao={"modo": "proxima_url", "url": "{{ $response.body.proxima }}",
                                                       "parar_quando": "resposta_vazia", "limite_paginas": 5, "intervalo_ms": 0})
    e, n = http_no(cfg)
    assert e.status == "erro" and n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []
    cfg["paginacao"]["url"] = "http://169.254.169.254/"
    e, n = http_no(cfg)
    assert n.erro_categoria == "bloqueado_ssrf"


def test_paginacao_intervalo_entre_paginas(http_no, paginas, h):
    """MV2-16: intervalo_ms espera entre as páginas (3 páginas, 2 esperas de 300 ms)."""
    cfg = h.cfg_http2(f"{paginas.base}/pagl", query=[{"nome": "page", "valor": "1"}], paginacao=pag(limite_paginas=3, intervalo_ms=300))
    t = time.monotonic()
    e, _ = http_no(cfg)
    assert e.status == "sucesso" and time.monotonic() - t >= 0.55


def test_paginacao_mascara_header_em_todas_as_paginas(http_no, paginas, h):
    """SEG-09/MV2-16: o header sensível fica mascarado nas requisições gravadas de todas as páginas."""
    cfg = h.cfg_http2(f"{paginas.base}/pagl", query=[{"nome": "page", "valor": "1"}],
                      headers=[{"nome": "Authorization", "valor": "Bearer SEGREDO-PAG"}], paginacao=pag(limite_paginas=3))
    e, n = http_no(cfg)
    assert len(n.requisicoes) == 3 and "SEGREDO-PAG" not in json.dumps(n.requisicoes) + json.dumps(_jsons(n))
    assert all(r["headers"] for r in n.requisicoes)


# ---- validação da config de paginação (MV2-16) ----

@pytest.fixture
def salvar_http(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    f = fabrica_fluxo(grafo=h.cadeia2())

    def _s(paginacao):
        g = h.grafo2([h.no2("g", "gatilho", titulo="Início"),
                      h.no2("x", "http", h.cfg_http2("https://api.exemplo.test/x", paginacao=paginacao), x=1)], [("g", "x")])
        return salvar_grafo(cliente_adm, f, g)

    return _s


def test_paginacao_valida_salva_sem_pendencia(salvar_http):
    """MV2-16: configs completas dos dois modos salvam sem pendência."""
    assert salvar_http(pag()).json()["pendencias"] == []
    r = salvar_http({"modo": "proxima_url", "url": "{{ $response.body.n }}", "parar_quando": "status", "codigos": [404]})
    assert r.status_code == 200 and r.json()["pendencias"] == []


@pytest.mark.parametrize("alteracao", [{"limite_paginas": 0}, {"limite_paginas": 101}, {"intervalo_ms": 5001}, {"intervalo_ms": -1},
                                       {"onde": "cookie"}, {"parar_quando": "nunca"}, {"nome": None}])
def test_paginacao_valor_fora_da_faixa_ou_ausente_e_pendencia(alteracao, salvar_http):
    """MV2-16: valor fora da faixa / chave obrigatória do modo ausente = pendência (200)."""
    p = pag()
    for k, v in alteracao.items():
        if v is None:
            p.pop(k)
        else:
            p[k] = v
    r = salvar_http(p)
    assert r.status_code == 200 and r.json()["pendencias"]


@pytest.mark.parametrize("alteracao", [{"extra": 1}, {"limite_paginas": "10"}, {"codigos": "404"}, {"intervalo_ms": 1.5}])
def test_paginacao_chave_desconhecida_ou_tipo_errado_e_400(alteracao, salvar_http):
    """MV2-16/MV2-02: chave desconhecida ou tipo errado = 400 de formato."""
    p = pag()
    p.update(alteracao)
    assert salvar_http(p).status_code == 400


def test_pendencia_proxima_url_sem_url(salvar_http):
    """MV2-16: proxima_url sem 'url' = pendência."""
    r = salvar_http({"modo": "proxima_url", "parar_quando": "resposta_vazia"})
    assert r.status_code == 200 and r.json()["pendencias"]


# ---------------- URL com base variável (MV2-19) ----------------

def test_base_variavel_no_inicio_da_url_nao_e_percent_encoded(http_no, liberado, h):
    """MV2-19: {{ expr }} no INÍCIO da url entra sem percent-encode (padrão baseUrl do n8n)."""
    e, n = http_no(h.cfg_http2("{{ $json.base }}/eco/ok"), [{"base": liberado.base}])
    assert e.status == "sucesso", e.erro_resumo
    assert liberado.hits("/eco/ok")[0]["rota"] == "/eco/ok"
    e, n = http_no(h.cfg_http2("={{ $json.base }}/eco/ok2"), [{"base": liberado.base}])
    assert e.status == "sucesso" and liberado.hits("/eco/ok2")


def test_valor_em_outra_posicao_continua_percent_encoded(http_no, liberado, h):
    """MV2-19: fora do início, o valor é percent-encoded (não injeta / ? # @)."""
    e, _ = http_no(h.cfg_http2(f"{liberado.base}/eco/{{{{ $json.v }}}}"), [{"v": "a/b?c#d@e"}])
    r = liberado.hits("/eco/")[0]
    assert e.status == "sucesso" and r["rota"].count("/") == 2 and "?" not in r["path"] and "#" not in r["path"]


@pytest.mark.parametrize("base", [
    "http://169.254.169.254", "http://localhost", "http://[::1]", "http://2130706433", "http://0177.0.0.1", "http://127.1",
    "file://", "ftp://exemplo.test", "javascript:", "http://user:senha@127.0.0.1", "http://exemplo.test\\@127.0.0.1",
    "http://127.0.0.1\r\nHost: x", "http://10.0.0.1", "http://[::ffff:127.0.0.1]",
])
def test_base_variavel_que_resolve_para_destino_proibido_e_bloqueada(base, http_no, liberado, h):
    """MV2-19/SEG-01..06/16: base vinda de expressão passa por TODAS as validações → bloqueado_ssrf (CR/LF pode ser 'placeholder'); nada chega ao servidor."""
    e, n = http_no(h.cfg_http2("{{ $json.base }}/api"), [{"base": base}])
    assert e.status == "erro" and n.erro_categoria in ("bloqueado_ssrf", "placeholder"), (base, n.erro_categoria)
    assert liberado.requisicoes == []


def test_base_variavel_para_servidor_local_nao_liberado_e_bloqueada(http_no, liberado, nao_liberado, h):
    """MV2-19/SEG-08: base apontando para outro servidor local (não liberado) → bloqueado_ssrf."""
    e, n = http_no(h.cfg_http2("{{ $json.base }}/ok"), [{"base": nao_liberado.base}])
    assert n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []


def test_base_variavel_com_redirect_para_proibido_e_bloqueada(http_no, liberado, h):
    """MV2-19/SEG-05: mesmo com base liberada, o redirect para destino proibido é revalidado."""
    liberado.rotas["/r"] = lambda req: (302, b"", {"Location": "http://169.254.169.254/"})
    e, n = http_no(h.cfg_http2("{{ $json.base }}/r"), [{"base": liberado.base}])
    assert n.erro_categoria == "bloqueado_ssrf"
