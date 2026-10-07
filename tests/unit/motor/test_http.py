import ipaddress
from urllib.parse import quote

import pytest

from apps.motor import http as cliente
from apps.motor.http import ErroHttp, categoria_de_status, ip_proibido, requisitar

pytestmark = pytest.mark.modulo("m3")


def pedir(url, **kw):
    kw.setdefault("metodo", "GET")
    return requisitar(url=url, **kw)


def bloqueia(url, servidor=None, **kw):
    with pytest.raises(ErroHttp) as erro:
        pedir(url, **kw)
    assert erro.value.categoria == "bloqueado_ssrf", url
    if servidor is not None:
        assert servidor.requisicoes == []
    return erro.value


# ---------------------------------------------------------------- IPs
@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.255.255.254",
        "0.0.0.0",
        "10.1.2.3",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "100.127.255.255",
        "224.0.0.1",
        "239.255.255.255",
        "240.0.0.1",
        "255.255.255.255",
        "198.18.0.1",
        "192.0.2.1",
        "::1",
        "::",
        "fc00::1",
        "fd12::1",
        "fe80::1",
        "fd00:ec2::254",
        "ff02::1",
        "fec0::1",
        "::ffff:127.0.0.1",
        "::ffff:7f00:1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "::127.0.0.1",
        "::10.0.0.1",
        "64:ff9b::7f00:1",
        "64:ff9b::a00:1",
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::1",
        "2002:a00:1::",
        "2002:a9fe:a9fe::1",
        "2001:0:7f00:1:0:0:80ff:fffe",  # teredo: servidor 127.0.0.1
        "2001:0:808:808:0:0:80ff:fffe",  # teredo: cliente 127.0.0.1 (xor)
    ],
)
def test_ips_proibidos(ip):
    assert ip_proibido(ip)
    assert ip_proibido(ipaddress.ip_address(ip))


@pytest.mark.parametrize(
    "ip",
    [
        "8.8.8.8",
        "1.1.1.1",
        "93.184.216.34",
        "2606:4700:4700::1111",
        "64:ff9b::808:808",
        "::ffff:8.8.8.8",
    ],
)
def test_ips_publicos_passam(ip):
    assert not ip_proibido(ip)


# ---------------------------------------------------------------- bloqueios sem conexão
@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1",
        "2130706433",
        "0177.0.0.1",
        "0x7f.0.0.1",
        "0x7f000001",
        "017700000001",
        "127.000.000.001",
        "0.0.0.0",
        "0",
        "10.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "[::1]",
        "[::ffff:127.0.0.1]",
        "[::ffff:7f00:1]",
        "[::127.0.0.1]",
        "[fc00::1]",
        "[fe80::1]",
        "[64:ff9b::7f00:1]",
        "[2002:7f00:1::1]",
        "[2001:0:7f00:1:0:0:80ff:fffe]",
        "localhost",
        "LOCALHOST",
        "localhost.",
        "localhost.localdomain",
        "app.localhost",
    ],
)
def test_hosts_proibidos_e_formas_alternativas(host, servidor):
    bloqueia(f"http://{host}:{servidor.porta}/ok", servidor)


def test_esquema_em_maiusculas_nao_foge(servidor):
    bloqueia(f"HTTP://127.0.0.1:{servidor.porta}/ok", servidor)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://exemplo.test/x",
        "gopher://exemplo.test/",
        "data:text/plain,hi",
        "javascript:alert(1)",
        "ws://exemplo.test/",
        "//exemplo.test/x",
        "exemplo.test/x",
        "",
        "http://",
        "http:///x",
        "http://exemplo.test:99999/",
        "http://exemplo.test:abc/",
        "http://exemplo .test/",
        "http://exemplo.test/\nx",
        "http://exemplo.test\\@127.0.0.1/",
    ],
)
def test_urls_invalidas_ou_com_esquema_proibido(url):
    bloqueia(url)


@pytest.mark.parametrize(
    "tpl",
    [
        "http://u:s@127.0.0.1:{p}/ok",
        "http://u@127.0.0.1:{p}/ok",
        "http://:s@127.0.0.1:{p}/ok",
        "http://x.test@127.0.0.1:{p}/ok",
        "http://127.0.0.1:{p}#@interno.exemplo.test/",
        "http://127.0.0.1:{p}@interno.exemplo.test/ok",
    ],
)
def test_credenciais_e_truques_de_arroba_mesmo_liberado(tpl, liberado):
    bloqueia(tpl.format(p=liberado.porta), liberado)


@pytest.mark.parametrize(
    "ips",
    [
        ["127.0.0.1"],
        ["10.0.0.5"],
        ["::1"],
        ["8.8.8.8", "127.0.0.1"],
        ["127.0.0.1", "8.8.8.8"],
        ["192.168.1.10", "::1"],
    ],
)
def test_nome_resolvendo_para_ip_proibido_valida_todos(ips, servidor, dns):
    chamadas = dns({"interno.exemplo.test": ips})
    erro = bloqueia(f"http://interno.exemplo.test:{servidor.porta}/ok", servidor)
    assert chamadas["interno.exemplo.test"] == 1
    for ip in ips:
        assert ip not in erro.mensagem


def test_dns_sem_resultado_e_categoria_dns(servidor, dns):
    dns({"nao-existe.exemplo.test": None})
    with pytest.raises(ErroHttp) as erro:
        pedir(f"http://nao-existe.exemplo.test:{servidor.porta}/ok")
    assert erro.value.categoria == "dns" and servidor.requisicoes == []


def test_liberacao_e_do_host_literal_mais_porta_exata(servidor, settings, dns):
    settings.MOTOR_SSRF_LIBERAR = [f"app.exemplo.test:{servidor.porta}"]
    dns({"app.exemplo.test": ["127.0.0.1"], "outro.exemplo.test": ["127.0.0.1"]})
    assert pedir(f"http://APP.exemplo.test:{servidor.porta}/ok")["status"] == 200
    bloqueia(f"http://outro.exemplo.test:{servidor.porta}/ok")  # outro nome, mesmo IP
    bloqueia(f"http://127.0.0.1:{servidor.porta}/ok")  # o IP literal não está na lista
    settings.MOTOR_SSRF_LIBERAR = [f"app.exemplo.test:{servidor.porta + 1}"]
    bloqueia(f"http://app.exemplo.test:{servidor.porta}/ok")  # porta diferente


def test_liberado_ainda_pina_no_ip_resolvido_e_manda_o_host_original(servidor, settings, dns):
    settings.MOTOR_SSRF_LIBERAR = [f"rebind.exemplo.test:{servidor.porta}"]
    chamadas = dns({"rebind.exemplo.test": [["127.0.0.1"], ["10.255.255.1"]]}, sequencial=True)
    resposta = pedir(f"http://rebind.exemplo.test:{servidor.porta}/eco")
    assert resposta["status"] == 200 and chamadas["rebind.exemplo.test"] == 1
    assert servidor.requisicoes[-1]["headers"]["host"] == f"rebind.exemplo.test:{servidor.porta}"


# ---------------------------------------------------------------- redirects
def _redir(servidor, destino):
    return f"{servidor.base}/redir-para?para={quote(destino, safe='')}"


@pytest.mark.parametrize(
    "destino",
    [
        "http://169.254.169.254/latest/",
        "http://10.0.0.1/",
        "http://[::1]:{p}/secret",
        "http://2130706433:{p}/secret",
        "file:///etc/passwd",
        "ftp://exemplo.test/x",
        "gopher://exemplo.test/x",
        "javascript:alert(1)",
        "data:text/plain,hi",
        "http://u:s@127.0.0.1:{p}/secret",
        "//10.0.0.1/x",
    ],
)
def test_redirect_para_destino_proibido_e_revalidado(destino, liberado):
    bloqueia(_redir(liberado, destino.format(p=liberado.porta)))
    assert not any(c.startswith("/secret") for c in liberado.caminhos)


def test_redirect_valido_e_seguido_e_relativo_funciona(liberado):
    assert pedir(_redir(liberado, "/ok"))["corpo"] == {"ok": True}
    assert pedir(f"{liberado.base}/redir/3")["status"] == 200


def test_ate_5_redirects_o_sexto_estoura(liberado):
    assert pedir(f"{liberado.base}/redir/5")["status"] == 200  # 5 saltos
    with pytest.raises(ErroHttp) as erro:
        pedir(f"{liberado.base}/redir/6")
    assert erro.value.categoria == "redirect_excessivo"


def test_max_redirects_vem_da_setting(liberado, settings):
    settings.MOTOR_MAX_REDIRECTS = 1
    assert pedir(f"{liberado.base}/redir/1")["status"] == 200
    with pytest.raises(ErroHttp):
        pedir(f"{liberado.base}/redir/2")


def test_redirect_sem_location_e_resposta_final(liberado):
    resposta = pedir(f"{liberado.base}/redir-sem-location")
    assert resposta["status"] == 302 and resposta["corpo"] == "semlocation"


def test_redirect_303_vira_get_sem_corpo_e_307_mantem(liberado):
    liberado.codigo_redirect = 303
    pedir(_redir(liberado, "/eco"), metodo="POST", corpo='{"a": 1}')
    assert liberado.requisicoes[-1]["metodo"] == "GET" and liberado.requisicoes[-1]["corpo"] == ""
    liberado.codigo_redirect = 307
    pedir(_redir(liberado, "/eco"), metodo="POST", corpo='{"a": 1}')
    assert (
        liberado.requisicoes[-1]["metodo"] == "POST"
        and liberado.requisicoes[-1]["corpo"] == '{"a": 1}'
    )


def test_redirect_entre_origens_nao_leva_credenciais(servidor, settings, dns):
    # mesma máquina, "origens" diferentes por nome; ambas liberadas
    settings.MOTOR_SSRF_LIBERAR = [
        f"a.exemplo.test:{servidor.porta}",
        f"b.exemplo.test:{servidor.porta}",
    ]
    dns({"a.exemplo.test": ["127.0.0.1"], "b.exemplo.test": ["127.0.0.1"]})
    origem = f"http://a.exemplo.test:{servidor.porta}"
    destino = f"http://b.exemplo.test:{servidor.porta}/eco"
    pedir(
        f"{origem}/redir-para?para={quote(destino, safe='')}",
        headers=[{"nome": "Authorization", "valor": "Bearer x"}, {"nome": "X-Ok", "valor": "1"}],
    )
    ultimo = servidor.requisicoes[-1]["headers"]
    assert "authorization" not in ultimo and ultimo["x-ok"] == "1"
    pedir(f"{origem}/eco", headers=[{"nome": "Authorization", "valor": "Bearer x"}])
    assert servidor.requisicoes[-1]["headers"]["authorization"] == "Bearer x"


# ---------------------------------------------------------------- requisição e resposta
def test_envia_metodo_headers_query_e_corpo(liberado):
    resposta = pedir(
        f"{liberado.base}/eco?a=1",
        metodo="POST",
        headers=[
            {"nome": "X-Teste", "valor": "ç ã"},
            {"nome": "Host", "valor": "evil.test"},
            {"nome": "Content-Length", "valor": "9999"},
        ],
        query=[{"nome": "q", "valor": "a b&c"}, {"nome": "q", "valor": "ç"}],
        corpo='{"x": 1}',
    )["corpo"]
    assert resposta["metodo"] == "POST"
    assert resposta["path"] == "/eco?a=1&q=a%20b%26c&q=%C3%A7"
    assert resposta["headers"]["host"] == f"127.0.0.1:{liberado.porta}"
    assert resposta["headers"]["content-type"] == "application/json"
    assert resposta["headers"]["content-length"] == "8"
    assert resposta["corpo"] == '{"x": 1}'


def test_content_type_do_usuario_prevalece(liberado):
    resposta = pedir(
        f"{liberado.base}/eco",
        metodo="PUT",
        headers=[{"nome": "content-type", "valor": "text/plain"}],
        corpo="oi",
    )["corpo"]
    assert resposta["headers"]["content-type"] == "text/plain"


def test_resposta_json_texto_charset_e_headers_minusculos(liberado):
    assert pedir(f"{liberado.base}/ok")["corpo"] == {"ok": True}
    assert pedir(f"{liberado.base}/texto")["corpo"] == "nao e json"
    assert pedir(f"{liberado.base}/latin1")["corpo"] == "ação"
    assert pedir(f"{liberado.base}/json-ruim")["corpo"] == "{nao json"
    assert pedir(f"{liberado.base}/nan")["corpo"] == '{"x": NaN}'  # constante não finita: texto
    resposta = pedir(f"{liberado.base}/cabecalhos")
    assert resposta["headers"]["x-publico"] == "visivel"
    assert resposta["headers"]["set-cookie"] == "a=1" and "Set-Cookie" not in resposta["headers"]


@pytest.mark.parametrize(
    ("codigo", "categoria"),
    [(404, "http_4xx"), (429, "http_4xx"), (500, "http_5xx"), (503, "http_5xx")],
)
def test_4xx_5xx_voltam_como_resposta_com_corpo(liberado, codigo, categoria):
    resposta = pedir(f"{liberado.base}/status/{codigo}")
    assert resposta["status"] == codigo and resposta["corpo"] == {"erro": "x"}
    assert categoria_de_status(codigo) == categoria


def test_categoria_de_status():
    assert [categoria_de_status(s) for s in (200, 301, 399, 400, 499, 500, 599)] == [
        None,
        None,
        None,
        "http_4xx",
        "http_4xx",
        "http_5xx",
        "http_5xx",
    ]


def test_corpo_maior_que_1mb_e_cortado_e_marcado(liberado):
    resposta = pedir(f"{liberado.base}/grande")
    assert resposta["truncado"] is True and len(resposta["corpo"]) == 1024 * 1024


def test_corpo_pequeno_nao_e_truncado_e_limite_vem_da_setting(liberado, settings):
    assert pedir(f"{liberado.base}/exato")["truncado"] is False
    settings.MOTOR_LIMITE_RESPOSTA = 100
    resposta = pedir(f"{liberado.base}/exato")
    assert resposta["truncado"] is True and len(resposta["corpo"]) == 100


def test_limite_conta_o_corpo_descompactado(liberado):
    resposta = pedir(f"{liberado.base}/gzip")
    assert resposta["truncado"] is True and len(resposta["corpo"]) == 1024 * 1024


def test_timeout_de_leitura(liberado, settings):
    settings.MOTOR_TIMEOUT_LEITURA = 0.3
    with pytest.raises(ErroHttp) as erro:
        pedir(f"{liberado.base}/lento")
    assert erro.value.categoria == "timeout"


def test_prazo_total_do_no(liberado, settings):
    settings.MOTOR_TIMEOUT_NO = 1
    with pytest.raises(ErroHttp) as erro:
        pedir(f"{liberado.base}/lento", prazo_s=0.1)
    assert erro.value.categoria == "timeout"


def test_conexao_recusada_e_categoria_conexao(settings):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{porta}"]
    with pytest.raises(ErroHttp) as erro:
        pedir(f"http://127.0.0.1:{porta}/x")
    assert erro.value.categoria == "conexao"
    assert "127.0.0.1" not in erro.value.mensagem and "Errno" not in erro.value.mensagem


def test_mensagens_sao_proprias_e_nao_vazam(servidor):
    erro = bloqueia(f"http://127.0.0.1:{servidor.porta}/ok")
    assert erro.mensagem == cliente.MENSAGENS["bloqueado_ssrf"]
    assert str(servidor.porta) not in erro.mensagem


def test_cliente_nao_usa_proxy_do_ambiente(liberado, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    assert pedir(f"{liberado.base}/ok")["status"] == 200


def test_nenhum_ambiente_libera_loopback_por_padrao():
    from config.settings import base, dev, teste

    assert base.MOTOR_SSRF_LIBERAR == dev.MOTOR_SSRF_LIBERAR == teste.MOTOR_SSRF_LIBERAR == []
