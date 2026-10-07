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


@pytest.mark.modulo("m3")
def test_headers_sensiveis_mascarados_na_entrada_mas_enviados_de_verdade(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: headers sensíveis (nomes da lista e qualquer nome com token/secret/senha/password/api-key) → '••••' na entrada; o valor real vai ao servidor."""
    hs = [{"nome": n, "valor": f"SEGREDO-{i}"} for i, n in enumerate(HEADERS_SENSIVEIS)] + [{"nome": "X-Publico", "valor": "visivel-ok"}]
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", headers=hs)))
    entrada = {h["nome"]: h["valor"] for h in no(e, "h1").entrada["headers"]}
    for n in HEADERS_SENSIVEIS:
        assert entrada[n] == MASCARA, n
    assert entrada["X-Publico"] == "visivel-ok"
    enviados = liberado.requisicoes[-1]["headers"]
    assert enviados["authorization"] == "SEGREDO-0" and enviados["x-api-key"].startswith("SEGREDO-")


@pytest.mark.modulo("m3")
def test_query_sensivel_mascarada_na_entrada_e_na_url_gravada(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: parâmetros de query sensíveis mascarados na entrada gravada (lista e URL final); o valor real vai ao servidor."""
    q = [{"nome": n, "valor": f"QSEGREDO-{i}"} for i, n in enumerate(QUERY_SENSIVEIS)] + [{"nome": "busca", "valor": "livre"}]
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", query=q)))
    h1 = no(e, "h1")
    entrada = {p["nome"]: p["valor"] for p in h1.entrada["query"]}
    for n in QUERY_SENSIVEIS:
        assert entrada[n] == MASCARA, n
    assert entrada["busca"] == "livre"
    assert "QSEGREDO" not in json.dumps(h1.entrada)
    assert "QSEGREDO-0" in liberado.requisicoes[-1]["path"]


@pytest.mark.modulo("m3")
def test_headers_sensiveis_da_resposta_mascarados_na_saida(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: Set-Cookie, X-Api-Key e qualquer header com 'token' na RESPOSTA → '••••' na saída; header público fica."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/cabecalhos")))
    saida = no(e, "h1").saida
    assert saida["headers"]["set-cookie"] == MASCARA
    assert saida["headers"]["x-api-key"] == MASCARA
    assert saida["headers"]["x-token-interno"] == MASCARA
    assert saida["headers"]["x-publico"] == "visivel"
    assert "SEGREDO" not in json.dumps(no(e, "s").saida)


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
    g = cadeia(cfg_http(f"{liberado.base}/valores"), cfg_http(f"{liberado.base}/eco", headers=[{"nome": "Authorization", "valor": "Bearer {{ anterior.corpo.v }}"}]))
    _, e, _ = executar(cliente_coordenador, g)
    assert no(e, "h2").entrada["headers"] == [{"nome": "Authorization", "valor": MASCARA}]


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
