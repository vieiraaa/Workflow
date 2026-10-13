"""Aceite M3: mascaramento de segredos e erros por categoria. Fontes: SEG-09, SEG-10, SEG-13, EXE-04, EXE-12."""

import json
import socket

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

MASCARA = "••••"
CATEGORIAS = {
    "bloqueado_ssrf", "timeout", "dns", "conexao", "tls", "resposta_grande", "redirect_excessivo",
    "http_4xx", "http_5xx", "placeholder", "json_invalido",
}
HEADERS_SENSIVEIS = [
    "Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie", "X-Api-Key", "X-API-KEY", "x-auth-token",
    "X-Secret", "X-Meu-Segredo-Secret", "X-Senha", "X-Password", "X-Minha-Api-Key", "X-Token", "My-TOKEN-Header",
]
QUERY_SENSIVEIS = ["token", "secret", "password", "senha", "api-key", "access_token", "API-KEY", "client_secret", "Password"]


def _h(r):
    return r.content.decode()


# T-060 (migração v2): com o nó HTTP em resposta_completa=true (MV2-12 L1), a SAÍDA é [{"json": {status, headers, corpo}}]
# e a requisição enviada (mascarada, SEG-09) fica em ExecucaoNo.requisicoes[] (MV2-15 B10) com a resposta em
# requisicoes[].resposta (MV2-22). O que o v1 chamava de "entrada gravada" do nó HTTP é requisicoes[].
def _j(n):
    assert len(n.saida) == 1, n.saida
    return n.saida[0]["json"]


@pytest.mark.modulo("m3")
def test_headers_sensiveis_mascarados_na_entrada_mas_enviados_de_verdade(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: headers sensíveis (nomes da lista e qualquer nome com token/secret/senha/password/api-key) → '••••' na
    requisição gravada (MV2-15 B10: requisicoes[].headers); o valor real vai ao servidor. SEG-21: o valor digitado
    (≥ 4 caracteres) refletido pelo servidor também sai mascarado da saída e de requisicoes[].resposta."""
    hs = [{"nome": n, "valor": f"SEGREDO-{i}"} for i, n in enumerate(HEADERS_SENSIVEIS)] + [{"nome": "X-Publico", "valor": "visivel-ok"}]
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", headers=hs)))
    h1 = no(e, "h1")
    assert len(h1.requisicoes) == 1
    entrada = {h["nome"]: h["valor"] for h in h1.requisicoes[0]["headers"]}
    for n in HEADERS_SENSIVEIS:
        assert entrada[n] == MASCARA, n
    assert entrada["X-Publico"] == "visivel-ok"
    enviados = liberado.requisicoes[-1]["headers"]
    assert enviados["authorization"] == "SEGREDO-0" and enviados["x-api-key"].startswith("SEGREDO-")
    # SEG-21: o /eco devolve os headers no corpo; os valores digitados não podem ficar em claro em lugar nenhum.
    assert "SEGREDO-" not in json.dumps(h1.requisicoes) and "SEGREDO-" not in json.dumps(h1.saida)
    assert _j(h1)["corpo"]["headers"]["x-publico"] == "visivel-ok"


@pytest.mark.modulo("m3")
def test_query_sensivel_mascarada_na_entrada_e_na_url_gravada(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: parâmetros de query sensíveis mascarados na requisição gravada (requisicoes[].query e url, MV2-15 B10);
    o valor real vai ao servidor. SEG-21: o valor refletido (/eco devolve a query) também sai mascarado."""
    q = [{"nome": n, "valor": f"QSEGREDO-{i}"} for i, n in enumerate(QUERY_SENSIVEIS)] + [{"nome": "busca", "valor": "livre"}]
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", query=q)))
    h1 = no(e, "h1")
    assert len(h1.requisicoes) == 1
    entrada = {p["nome"]: p["valor"] for p in h1.requisicoes[0]["query"]}
    for n in QUERY_SENSIVEIS:
        assert entrada[n] == MASCARA, n
    assert entrada["busca"] == "livre"
    assert "QSEGREDO" not in json.dumps(h1.requisicoes) and "QSEGREDO" not in json.dumps(h1.saida)  # SEG-21
    assert "QSEGREDO" not in json.dumps(h1.entrada)
    assert "QSEGREDO-0" in liberado.requisicoes[-1]["path"]


@pytest.mark.modulo("m3")
def test_headers_sensiveis_da_resposta_mascarados_na_saida(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: Set-Cookie, X-Api-Key e qualquer header com 'token' na RESPOSTA → '••••' na saída; header público fica."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/cabecalhos")))
    h1 = no(e, "h1")
    saida = _j(h1)  # MV2-12 L1: resposta_completa → {status, headers, corpo}
    for hs in (saida["headers"], h1.requisicoes[0]["resposta"]["headers"]):  # MV2-22: também na resposta gravada
        assert hs["set-cookie"] == MASCARA
        assert hs["x-api-key"] == MASCARA
        assert hs["x-token-interno"] == MASCARA
        assert hs["x-publico"] == "visivel"
    assert "SEGREDO" not in json.dumps(no(e, "s").saida) and "SEGREDO" not in json.dumps(h1.requisicoes)


@pytest.mark.modulo("m3")
def test_nenhuma_tela_mostra_segredo(cliente_coordenador, cliente_adm, liberado, executar, cadeia, cfg_http):
    """SEG-09: detalhe e lista não exibem os valores secretos (request e response); exibem a máscara."""
    g = cadeia(cfg_http(f"{liberado.base}/cabecalhos", headers=[{"nome": "Authorization", "valor": "Bearer SEGREDO-TELA"}], query=[{"nome": "token", "valor": "SEGREDO-QUERY"}]))
    _, e, _ = executar(cliente_coordenador, g)
    for c in (cliente_coordenador, cliente_adm):
        for url in (reverse("execucoes:detalhe", kwargs={"pk": e.pk}), reverse("execucoes:lista")):
            h = _h(c.get(url))
            for s in ("SEGREDO-TELA", "SEGREDO-QUERY", "SEGREDO-COOKIE-RESP", "SEGREDO-APIKEY-RESP", "SEGREDO-TOKEN-RESP"):
                assert s not in h, (url, s)
    assert MASCARA in _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))


@pytest.mark.modulo("m3")
def test_placeholder_em_header_sensivel_tambem_e_mascarado(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09/EXE-12: valor vindo de placeholder num header sensível é gravado mascarado (entrada já resolvida)."""
    g = cadeia(cfg_http(f"{liberado.base}/valores"), cfg_http(f"{liberado.base}/eco", headers=[{"nome": "Authorization", "valor": "Bearer {{ $json.corpo.v }}"}]))  # MV2-03: anterior → $json
    _, e, _ = executar(cliente_coordenador, g)
    # MV2-15 B10: a requisição já resolvida e mascarada fica em requisicoes[]
    assert no(e, "h2").requisicoes[0]["headers"] == [{"nome": "Authorization", "valor": MASCARA}]


@pytest.mark.modulo("m3")
def test_erro_dns_so_categoria_e_mensagem_propria(cliente_coordenador, servidor, dns, executar, cadeia, cfg_http, no):
    """SEG-10: dns → categoria própria, sem texto cru do driver nem do getaddrinfo."""
    dns({"nao-existe.exemplo.test": None})
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://nao-existe.exemplo.test:{servidor.porta}/ok")))
    h1 = no(e, "h1")
    assert h1.erro_categoria == "dns"
    for cru in ("gaierror", "Errno", "Name or service not known", "Traceback", "httpx", "socket"):
        assert cru not in h1.erro_mensagem, cru


@pytest.mark.modulo("m3")
def test_erro_conexao_recusada(cliente_coordenador, settings, executar, cadeia, cfg_http, no):
    """SEG-10: porta fechada (liberada) → categoria conexao, sem Errno/ConnectError/IP na mensagem."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{porta}"]
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://127.0.0.1:{porta}/ok")))
    h1 = no(e, "h1")
    assert h1.erro_categoria == "conexao"
    for cru in ("Errno", "ConnectError", "httpx", "Connection refused", "Traceback", "127.0.0.1"):
        assert cru not in h1.erro_mensagem, cru


@pytest.mark.modulo("m3")
def test_erro_tls_em_servidor_sem_tls(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-10: https contra servidor HTTP puro → categoria tls, sem detalhe de OpenSSL na mensagem."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"https://127.0.0.1:{liberado.porta}/ok")))
    h1 = no(e, "h1")
    assert h1.erro_categoria == "tls"
    for cru in ("SSL:", "WRONG_VERSION", "ssl.", "openssl", "Traceback", "httpx"):
        assert cru.lower() not in h1.erro_mensagem.lower(), cru


@pytest.mark.modulo("m3")
def test_todas_as_falhas_usam_so_categorias_do_seg10(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-10: qualquer erro de nó usa uma categoria da lista fechada e uma mensagem não vazia."""
    for caminho in ("/status/404", "/status/500", "/grande-inexistente-404"):
        _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}{caminho}")))
        h1 = no(e, "h1")
        assert h1.erro_categoria in CATEGORIAS and h1.erro_mensagem


@pytest.mark.modulo("m3")
def test_mensagem_de_ssrf_nao_vaza_ip_resolvido(cliente_coordenador, servidor, dns, executar, cadeia, cfg_http, no):
    """SEG-10: bloqueio por IP resolvido não expõe o IP interno na mensagem mostrada ao usuário."""
    dns({"intranet.exemplo.test": ["10.20.30.40"]})
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://intranet.exemplo.test:{servidor.porta}/ok")))
    h1 = no(e, "h1")
    assert h1.erro_categoria == "bloqueado_ssrf" and "10.20.30.40" not in h1.erro_mensagem
    h = _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert "10.20.30.40" not in h


@pytest.mark.modulo("m3")
def test_grafo_snapshot_tambem_e_mascarado(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """SEG-16.5/SEG-09: segredo digitado no nó não fica no grafo_snapshot (headers e query sensíveis → '••••')."""
    g = cadeia(cfg_http(f"{liberado.base}/eco", headers=[{"nome": "Authorization", "valor": "Bearer SEGREDO-SNAP"}, {"nome": "X-Publico", "valor": "visivel"}], query=[{"nome": "api-key", "valor": "SEGREDO-SNAP-Q"}, {"nome": "busca", "valor": "livre"}]))
    _, e, f = executar(cliente_coordenador, g)
    bruto = json.dumps(e.grafo_snapshot)
    assert "SEGREDO-SNAP" not in bruto
    cfg = next(n for n in e.grafo_snapshot["nos"] if n["id"] == "h1")["config"]
    assert {h["nome"]: h["valor"] for h in cfg["headers"]} == {"Authorization": MASCARA, "X-Publico": "visivel"}
    assert {q["nome"]: q["valor"] for q in cfg["query"]} == {"api-key": MASCARA, "busca": "livre"}
    f.refresh_from_db()
    assert "SEGREDO-SNAP" in json.dumps(f.grafo)  # o fluxo em si continua com o valor real; só o histórico é mascarado


@pytest.mark.modulo("m3")
def test_segredo_digitado_refletido_no_corpo_da_resposta_e_mascarado_por_valor(cliente_coordenador, cliente_adm, liberado, executar, cadeia, cfg_http, no):
    """SEG-21 (SUBSTITUI o teste da SEG-16 item 6, que afirmava que o segredo refletido NÃO era mascarado): valores
    digitados em header/query sensíveis — inclusive na query da própria url — com ≥ 4 caracteres são mascarados POR VALOR
    ('••••') onde reaparecerem: saída do nó, requisicoes[].resposta (headers e corpo) e tela. Header público refletido
    continua visível (SEG-09 só cobre os sensíveis)."""
    g = cadeia(cfg_http(f"{liberado.base}/eco?token=SEGREDO-NA-URL-77",
                        headers=[{"nome": "Authorization", "valor": "Bearer SEGREDO-REFLETIDO-123"},
                                 {"nome": "X-Api-Key", "valor": "SEGREDO-APIKEY-456"},
                                 {"nome": "X-Publico", "valor": "ECO-NO-CORPO"}],
                        query=[{"nome": "password", "valor": "SEGREDO-QUERY-789"}]))
    _, e, _ = executar(cliente_coordenador, g)
    h1 = no(e, "h1")
    assert e.status == "sucesso"
    segredos = ("SEGREDO-REFLETIDO-123", "SEGREDO-APIKEY-456", "SEGREDO-QUERY-789", "SEGREDO-NA-URL-77")
    # o servidor recebeu os valores reais (o mascaramento é só na gravação)
    assert liberado.requisicoes[-1]["headers"]["x-api-key"] == "SEGREDO-APIKEY-456"
    for onde, bruto in (("saida", json.dumps(h1.saida)), ("requisicoes", json.dumps(h1.requisicoes)),
                        ("saida do nó Saída", json.dumps(no(e, "s").saida)), ("entrada do nó Saída", json.dumps(no(e, "s").entrada))):
        for seg in segredos:
            assert seg not in bruto, (onde, seg)
    corpo = _j(h1)["corpo"]
    assert MASCARA in json.dumps(corpo, ensure_ascii=False)
    assert corpo["headers"]["x-publico"] == "ECO-NO-CORPO"
    assert MASCARA in h1.requisicoes[0]["resposta"]["corpo"]
    for c in (cliente_coordenador, cliente_adm):
        h = _h(c.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
        for seg in segredos:
            assert seg not in h, seg
        assert MASCARA in h


@pytest.mark.modulo("m3")
def test_mascara_por_valor_so_a_partir_de_4_caracteres(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-21 (limite): valor digitado com 4 caracteres é mascarado por valor onde reaparecer; com 3 não é (o header
    segue mascarado POR NOME em requisicoes[].headers, SEG-09)."""
    g = cadeia(cfg_http(f"{liberado.base}/eco", headers=[{"nome": "X-Api-Key", "valor": "Zq7"}, {"nome": "X-Token", "valor": "Yw8L"},
                                                          {"nome": "X-Publico-A", "valor": "Zq7"}, {"nome": "X-Publico-B", "valor": "Yw8L"}]))
    _, e, _ = executar(cliente_coordenador, g)
    h1 = no(e, "h1")
    hs = {h["nome"]: h["valor"] for h in h1.requisicoes[0]["headers"]}
    assert hs["X-Api-Key"] == MASCARA and hs["X-Token"] == MASCARA
    # o /eco devolve os headers; os públicos só podem ser escondidos por VALOR (nome não sensível)
    refletido = _j(h1)["corpo"]["headers"]
    assert refletido["x-publico-a"] == "Zq7"  # 3 caracteres: sem mascaramento por valor
    assert refletido["x-publico-b"] == MASCARA  # 4 caracteres: mascarado por valor
    assert "Yw8L" not in json.dumps(h1.saida) and "Yw8L" not in json.dumps(h1.requisicoes)
