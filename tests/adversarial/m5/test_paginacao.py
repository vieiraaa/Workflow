"""Adversarial M5: paginação do nó HTTP (NOV-05, MV2-16, MV2-24 d) — loop, SSRF por página, $response gigante. Só servidor local."""

import json
import time

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]


def pag(**kw):
    p = {"modo": "atualizar_parametro", "onde": "query", "nome": "page", "valor": "{{ $pageCount + 1 }}",
         "parar_quando": "resposta_vazia", "limite_paginas": 10, "intervalo_ms": 0}
    p.update(kw)
    return p


def prox(url="{{ $response.body.next }}", **kw):
    p = {"modo": "proxima_url", "url": url, "parar_quando": "expressao", "expressao": "{{ !$response.body.next }}",
         "limite_paginas": 10, "intervalo_ms": 0}
    p.update(kw)
    return p


@pytest.fixture
def srv(liberado):
    liberado.rotas["/sempre"] = lambda req: (200, [{"x": 1}], None)
    liberado.rotas["/mesma"] = lambda req: (200, {"d": [1], "next": f"{liberado.base}/mesma"}, None)
    return liberado


# ---------------- loop infinito ----------------

@pytest.mark.parametrize("limite", [1, 3, 10, 100])
def test_servidor_que_nunca_esvazia_para_no_limite_de_paginas(limite, http_no, srv, h):
    """MV2-16: resposta_vazia nunca ocorre → para EXATAMENTE em limite_paginas, sem erro (1..100)."""
    e, n = http_no(h.cfg_http2(f"{srv.base}/sempre", query=[{"nome": "page", "valor": "1"}], paginacao=pag(limite_paginas=limite)))
    assert e.status == "sucesso" and len(srv.hits("/sempre")) == limite


def test_proxima_url_que_aponta_para_a_mesma_pagina_para_no_limite(http_no, srv, h):
    """MV2-16: proxima_url cíclica (sempre a mesma URL) → para em limite_paginas (padrão 10), sem erro e sem loop infinito."""
    e, n = http_no(h.cfg_http2(f"{srv.base}/mesma", paginacao=prox(parar_quando="resposta_vazia")))
    assert e.status == "sucesso" and len(srv.hits("/mesma")) == 10


def test_parar_quando_expressao_que_nunca_fica_verdadeira_respeita_o_limite(http_no, srv, h):
    """MV2-16: parar_quando=expressao sempre falsa → limite de páginas (100) é o teto; nunca passa dele."""
    e, n = http_no(h.cfg_http2(f"{srv.base}/sempre", query=[{"nome": "page", "valor": "1"}],
                               paginacao=pag(parar_quando="expressao", expressao="{{ false }}", limite_paginas=100)))
    assert e.status == "sucesso" and len(srv.hits("/sempre")) == 100


def test_intervalo_de_5s_com_100_paginas_e_cortado_pelo_limite_de_60s_da_execucao(http_no, srv, h, settings):
    """EXE-13/MV2-16: intervalo_ms=5000 × 100 páginas não prende a execução: MOTOR_TIMEOUT_EXECUCAO (aqui 2 s) a encerra com erro
    `timeout` em poucos segundos e sem disparar as 100 requisições."""
    settings.MOTOR_TIMEOUT_EXECUCAO = 2
    t0 = time.time()
    e, n = http_no(h.cfg_http2(f"{srv.base}/sempre", query=[{"nome": "page", "valor": "1"}],
                               paginacao=pag(limite_paginas=100, intervalo_ms=5000)))
    assert time.time() - t0 < 25
    assert e.status == "erro" and n.erro_categoria == "timeout"
    assert len(srv.hits("/sempre")) <= 3


@pytest.mark.parametrize("campo,valor", [("limite_paginas", 0), ("limite_paginas", 101), ("limite_paginas", -5), ("limite_paginas", 10 ** 9),
                                         ("intervalo_ms", -1), ("intervalo_ms", 5001), ("intervalo_ms", 10 ** 9)])
def test_limites_fora_da_faixa_viram_pendencia_e_nao_executam(campo, valor, cliente_adm, fabrica_fluxo, salvar_grafo, h, srv, modelos):
    """MV2-16: limite_paginas fora de 1..100 e intervalo_ms fora de 0..5000 = pendência ao salvar (200); o fluxo não executa e o
    servidor não recebe nenhuma requisição."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{srv.base}/sempre", query=[{"nome": "page", "valor": "1"}], paginacao=pag(**{campo: valor})), x=1))
    f = fabrica_fluxo(status="rascunho")
    r = salvar_grafo(cliente_adm, f, g)
    assert r.status_code == 200 and any(p["no"] == "h" for p in r.json()["pendencias"])
    from django.urls import reverse
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert srv.requisicoes == [] and modelos.Execucao.objects.count() == 0


@pytest.mark.parametrize("campo,valor", [("limite_paginas", "10"), ("limite_paginas", 1.5), ("limite_paginas", True), ("limite_paginas", None),
                                         ("intervalo_ms", "0"), ("modo", "xyz"), ("onde", "cookie"), ("parar_quando", "nunca"), ("codigos", "404"),
                                         ("extra", 1)])
def test_tipos_errados_na_paginacao_sao_400_de_formato(campo, valor, cliente_adm, fabrica_fluxo, salvar_grafo, h, srv):
    """MV2-16/MV2-02/MV2-12 L3: chave desconhecida, tipo errado ou ENUM inválido em config.paginacao = 400 de formato; nada gravado."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{srv.base}/sempre", paginacao=pag(**{campo: valor})), x=1))
    f = fabrica_fluxo()
    antes = json.loads(json.dumps(f.grafo))
    r = salvar_grafo(cliente_adm, f, g)
    assert r.status_code == 400, (campo, valor)
    f.refresh_from_db()
    assert f.grafo == antes


# ---------------- SSRF por página ----------------

DESTINOS = [
    "http://169.254.169.254/latest/meta-data/", "http://[::1]:{p}/secret", "http://0x7f.1:{p}/secret", "http://2130706433:{p}/secret",
    "http://127.0.0.1:{p}/secret", "http://localhost:{p}/secret", "http://user:senha@127.0.0.1:{p}/secret", "http://10.0.0.1/", "http://192.168.0.1/",
    "http://[::ffff:127.0.0.1]:{p}/secret", "http://127.0.0.1\\@exemplo.test:{p}/secret", "http://exemplo.test@127.0.0.1:{p}/secret",
    "http://127.0.0.1%2509:{p}/x", "file:///etc/passwd", "gopher://127.0.0.1:{p}/_x", "ftp://127.0.0.1/x", "javascript:alert(1)", "data:text/plain,x",
    "//127.0.0.1:{p}/secret", "http://0:{p}/secret", "http://127.1:{p}/secret",
]


@pytest.mark.parametrize("destino", DESTINOS)
def test_proxima_url_para_destino_proibido_e_bloqueada_a_partir_da_pagina_2(destino, http_no, srv, nao_liberado, h):
    """SEG-02..06/MV2-16 (SSRF por PÁGINA): a 1ª página é permitida e devolve em `next` um destino proibido (loopback/metadata/privado/
    esquema/credencial na URL/obfuscação); o nó falha (bloqueado_ssrf, ou erro de expressão/esquema) e NENHUMA requisição chega ao
    servidor-alvo."""
    alvo = destino.format(p=nao_liberado.porta)
    srv.rotas["/p1"] = lambda req: (200, {"d": [1], "next": alvo}, None)
    e, n = http_no(h.cfg_http2(f"{srv.base}/p1", paginacao=prox()))
    assert e.status == "erro", (e.status, n.status)
    assert n.erro_categoria in ("bloqueado_ssrf", "expressao", "placeholder", "paginacao", "dns"), n.erro_categoria  # dns: host ofuscado que nem resolve
    assert nao_liberado.requisicoes == [] and srv.hits("/secret") == []
    assert len(srv.hits("/p1")) == 1


def test_proxima_url_com_dns_que_resolve_para_ip_interno_e_bloqueada(http_no, srv, nao_liberado, h, monkeypatch):
    """SEG-03/04: `next` com NOME que resolve para IP privado (DNS simulado) → bloqueado_ssrf na página 2; nada chega ao alvo."""
    import socket
    orig = socket.getaddrinfo

    def falso(host, porta, *a, **k):
        if host == "interno.exemplo.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", porta or 0))]
        return orig(host, porta, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", falso)
    srv.rotas["/p1"] = lambda req: (200, {"d": [1], "next": f"http://interno.exemplo.test:{nao_liberado.porta}/x"}, None)
    e, n = http_no(h.cfg_http2(f"{srv.base}/p1", paginacao=prox()))
    assert e.status == "erro" and n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []


def test_redirect_na_segunda_pagina_para_destino_proibido_e_bloqueado(http_no, srv, nao_liberado, h):
    """SEG-05: a página 2 responde 302 → loopback não liberado: bloqueado; o destino do redirect nunca recebe requisição."""
    def p(req):
        n = int(req["query"].get("page", ["1"])[0])
        if n == 1:
            return 200, [{"x": 1}], None
        return 302, b"", {"Location": f"{nao_liberado.base}/secret"}
    srv.rotas["/rp"] = p
    e, n = http_no(h.cfg_http2(f"{srv.base}/rp", query=[{"nome": "page", "valor": "1"}], paginacao=pag()))
    assert e.status == "erro" and n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []


def test_atualizar_parametro_nao_muda_o_host_de_destino(http_no, srv, nao_liberado, h):
    """SEG-02/MV2-16: `onde=query` com nome/valor hostis (CRLF, &, #, host) altera só a query: a conexão segue ao host configurado e
    nenhum header extra é injetado."""
    for valor in (f"{{{{ '127.0.0.1:{nao_liberado.porta}/secret' }}}}", "{{ 'a&b=2#x' }}", "{{ 'a\\r\\nX-Evil: 1' }}"):
        srv.requisicoes.clear()
        e, n = http_no(h.cfg_http2(f"{srv.base}/sempre", query=[{"nome": "page", "valor": "1"}],
                                   paginacao=pag(valor=valor, limite_paginas=2)))
        assert nao_liberado.requisicoes == []
        for r in srv.requisicoes:
            assert "x-evil" not in r["headers"]
            assert r["rota"] == "/sempre"


def test_atualizar_parametro_no_header_com_crlf_e_recusado(http_no, srv, h):
    """SEG-16 (3)/MV2-16: valor de header paginado com CR/LF → erro categorizado (placeholder) sem enviar a página 2 com header injetado."""
    e, n = http_no(h.cfg_http2(f"{srv.base}/sempre", headers=[{"nome": "X-Page", "valor": "1"}],
                               paginacao=pag(onde="header", nome="X-Page", valor="{{ 'a\\r\\nX-Evil: 1' }}", limite_paginas=3)))
    assert e.status == "erro"
    assert all("x-evil" not in r["headers"] for r in srv.requisicoes)


# ---------------- $response gigante ----------------

def test_response_gigante_na_proxima_url_falha_com_resposta_grande_e_para(http_no, srv, h, settings):
    """MV2-24 (d)/SEG-07: página cortada no limite lido e usada em `$response` (proxima_url/parar_quando) → o nó falha com
    `resposta_grande`; não segue para a página seguinte (1 requisição)."""
    settings.MOTOR_LIMITE_RESPOSTA = 4096
    srv.rotas["/gg"] = lambda req: (200, b'{"next": "' + b"x" * 100_000 + b'"}', {"Content-Type": "application/json"})
    e, n = http_no(h.cfg_http2(f"{srv.base}/gg", paginacao=prox(limite_paginas=5)))
    assert e.status == "erro" and n.erro_categoria == "resposta_grande"
    assert len(srv.hits("/gg")) == 1


def test_gzip_bomba_em_pagina_nao_estoura_memoria_nem_tempo(http_no, srv, h):
    """SEG-07: cada página conta para os limites: gzip de ~300 MB na página 1 é cortado em 1 MiB; execução rápida, sem 500."""
    import gzip
    bomba = gzip.compress(b"0" * (300 * 1024 * 1024), compresslevel=1)
    srv.rotas["/bomba"] = lambda req: (200, bomba, {"Content-Type": "text/plain", "Content-Encoding": "gzip"})
    t0 = time.time()
    e, n = http_no(h.cfg_http2(f"{srv.base}/bomba", paginacao=pag(limite_paginas=3, parar_quando="expressao", expressao="{{ false }}")))
    assert time.time() - t0 < 60 and e.status in ("sucesso", "erro")
    assert all(r["resposta"]["truncado"] for r in n.requisicoes)


def test_paginas_grandes_acumuladas_respeitam_limite_de_itens(http_no, srv, h):
    """MV2-01: 100 páginas × 200 itens = 20.000 itens > 10.000 → erro `limite_itens` (sem estourar memória/tempo)."""
    srv.rotas["/m"] = lambda req: (200, [{"i": i} for i in range(200)], None)
    t0 = time.time()
    e, n = http_no(h.cfg_http2(f"{srv.base}/m", query=[{"nome": "page", "valor": "1"}], paginacao=pag(limite_paginas=100)))
    assert e.status == "erro" and n.erro_categoria == "limite_itens" and time.time() - t0 < 60


# ---------------- mascaramento em cada página ----------------

def test_segredo_digitado_refletido_em_toda_pagina_e_mascarado(http_no, srv, h):
    """SEG-21/MV2-22: cada página que reflete o Authorization digitado fica mascarada em requisicoes[].resposta (headers e corpo) e na saída."""
    seg = "SEGREDO-PAG-77aa31"
    srv.rotas["/refl"] = lambda req: (200, [{"auth": req["headers"].get("authorization"), "n": 1}], {"X-Eco": req["headers"].get("authorization", "")})
    e, n = http_no(h.cfg_http2(f"{srv.base}/refl", query=[{"nome": "page", "valor": "1"}], headers=[{"nome": "Authorization", "valor": f"Bearer {seg}"}],
                               paginacao=pag(limite_paginas=3)))
    assert len(n.requisicoes) == 3
    assert seg not in json.dumps(n.requisicoes) and seg not in json.dumps(n.saida)
    assert all("••••" in json.dumps(r["resposta"], ensure_ascii=False) for r in n.requisicoes)
