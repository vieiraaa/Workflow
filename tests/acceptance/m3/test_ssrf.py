"""Aceite M3: SSRF com o motor REAL (sem liberar). Fontes: SEG-01..06, SEG-08, SEG-10, EXE-02."""

import socket
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.django_db


def _bloqueia(cliente, executar, cadeia, cfg_http, no, servidor, url, esperar_criada=True):
    _, e, _ = executar(cliente, cadeia(cfg_http(url)))
    if not esperar_criada and e is None:
        return None
    assert e is not None, url
    h1 = no(e, "h1")
    assert h1.status == "erro" and h1.erro_categoria == "bloqueado_ssrf", (url, h1.erro_categoria)
    assert no(e, "s").status == "nao_executado" and e.status == "erro"
    assert servidor.hits == [], (url, servidor.hits)
    return e


def _ipv4(p):
    return [
        "127.0.0.1", "127.1", "127.0.0.2", "127.255.255.254", "2130706433", "0177.0.0.1", "0x7f.0.0.1",
        "0x7f000001", "017700000001", "127.000.000.001", "0.0.0.0", "0", "10.0.0.1", "10.255.255.255",
        "172.16.0.1", "172.31.255.255", "192.168.0.1", "192.168.255.255", "169.254.169.254", "169.254.0.1",
        "100.64.0.1", "100.127.255.255", "224.0.0.1", "239.255.255.255", "240.0.0.1", "255.255.255.255",
    ]


IPV6 = [
    "[::1]", "[::]", "[::ffff:127.0.0.1]", "[::ffff:7f00:1]", "[0:0:0:0:0:ffff:127.0.0.1]", "[::127.0.0.1]",
    "[fc00::1]", "[fd12:3456:789a::1]", "[fe80::1]", "[fd00:ec2::254]", "[ff02::1]", "[::ffff:10.0.0.1]",
    "[::ffff:169.254.169.254]", "[64:ff9b::7f00:1]", "[64:ff9b::a00:1]", "[64:ff9b::a9fe:a9fe]",
    "[2002:7f00:1::1]", "[2002:a00:1::]", "[2002:a9fe:a9fe::1]", "[2001:0:7f00:1:0:0:80ff:fffe]",
]


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("host", _ipv4(0))
def test_ipv4_proibidos_e_formas_alternativas(host, cliente_coordenador, servidor, executar, cadeia, cfg_http, no):
    """SEG-02/SEG-03: loopback, privados, link-local, CGNAT, multicast, reservados e formas decimal/octal/hex/abreviada/zeros → bloqueado_ssrf, sem conexão."""
    _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, servidor, f"http://{host}:{servidor.porta}/ok")


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("host", IPV6)
def test_ipv6_e_formas_embutidas(host, cliente_coordenador, servidor, executar, cadeia, cfg_http, no):
    """SEG-02: ::1, mapeado/compatível, ULA, link-local, multicast, NAT64, 6to4 e Teredo com IPv4 proibido → bloqueado_ssrf."""
    _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, servidor, f"http://{host}:{servidor.porta}/ok")


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("url_base", ["HTTP://127.0.0.1", "Http://localhost", "hTTp://[::1]"])
def test_esquema_em_maiusculas_nao_foge_da_validacao_de_ip(url_base, cliente_coordenador, servidor, executar, cadeia, cfg_http, no):
    """SEG-01/SEG-02: esquema sem diferenciar maiúsculas; o IP continua validado."""
    _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, servidor, f"{url_base}:{servidor.porta}/ok")


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("nome", ["localhost", "LOCALHOST", "localhost.", "localhost.localdomain"])
def test_localhost_e_variantes(nome, cliente_coordenador, servidor, executar, cadeia, cfg_http, no):
    """SEG-03: 'localhost' (e variantes) → bloqueado_ssrf."""
    _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, servidor, f"http://{nome}:{servidor.porta}/ok")


@pytest.mark.modulo("m3")
@pytest.mark.parametrize(
    "ips",
    [["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["::1"], ["::ffff:127.0.0.1"], ["8.8.8.8", "127.0.0.1"], ["127.0.0.1", "8.8.8.8"], ["192.168.1.10", "::1"], ["fd00:ec2::254"]],
)
def test_nome_que_resolve_para_proibido_e_bloqueado(ips, cliente_coordenador, servidor, dns, executar, cadeia, cfg_http, no):
    """SEG-02/SEG-03: TODOS os IPs do DNS são validados; qualquer um proibido bloqueia (inclusive misto público+privado)."""
    chamadas = dns({"interno.exemplo.test": ips})
    e = _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, servidor, f"http://interno.exemplo.test:{servidor.porta}/ok")
    assert chamadas["interno.exemplo.test"] >= 1
    for ip in ips:
        assert ip not in no(e, "h1").erro_mensagem


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("destino", [
    "file:///etc/passwd", "ftp://exemplo.test/x", "gopher://exemplo.test/x", "data:text/plain,hi", "javascript:alert(1)",
    "FILE:///etc/passwd", "ws://exemplo.test/", "dict://exemplo.test/", "ldap://exemplo.test/", "//exemplo.test/x", "exemplo.test/x",
])
def test_esquemas_nao_http_nunca_saem(destino, cliente_coordenador, servidor, executar, cadeia, cfg_http, no):
    """SEG-01: esquema fora de http/https → pendência (sem execução) ou bloqueado_ssrf; nunca conexão."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(destino)))
    assert e is None or no(e, "h1").erro_categoria == "bloqueado_ssrf"
    assert servidor.hits == []


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("url_tpl", [
    "http://usuario:senha@127.0.0.1:{p}/ok", "http://usuario@127.0.0.1:{p}/ok", "http://:senha@127.0.0.1:{p}/ok",
    "http://evil.exemplo.test@127.0.0.1:{p}/ok", "http://evil.exemplo.test:80@127.0.0.1:{p}/ok",
])
def test_credenciais_na_url_sao_recusadas_mesmo_com_o_host_liberado(url_tpl, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-06: user:senha@host é recusado (host real liberado, então só a regra de credenciais pode barrar) — sem conexão."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(url_tpl.format(p=liberado.porta))))
    assert e is None or (no(e, "h1").status == "erro" and no(e, "h1").erro_categoria == "bloqueado_ssrf")
    assert liberado.hits == []


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("url_tpl", [
    "http://127.0.0.1:{p}@interno.exemplo.test/ok", "http://127.0.0.1:{p}#@interno.exemplo.test/", "http://interno.exemplo.test\\@127.0.0.1:{p}/ok",
    "http://interno.exemplo.test:{p}\\@127.0.0.1/ok",
])
def test_truques_com_arroba_e_barra_nao_enganam_o_parser(url_tpl, cliente_coordenador, liberado, dns, executar, cadeia, cfg_http, no):
    """SEG-06: o '@' (e '\\\\' / '#') não pode fazer o motor validar um host e conectar em outro."""
    dns({"interno.exemplo.test": ["10.0.0.5"]})
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(url_tpl.format(p=liberado.porta))))
    assert e is None or no(e, "h1").erro_categoria == "bloqueado_ssrf"
    assert liberado.hits == []


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("destino", [
    "http://169.254.169.254/latest/meta-data/", "http://localhost:{p}/secret", "http://10.0.0.1/", "http://[::1]:{p}/secret",
    "http://2130706433:{p}/secret", "file:///etc/passwd", "ftp://exemplo.test/x", "gopher://exemplo.test/x", "javascript:alert(1)",
    "data:text/plain,hi", "http://usuario:senha@127.0.0.1:{p}/secret",
])
def test_redirect_para_destino_proibido_e_revalidado(destino, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-05: cada destino de redirect é revalidado (esquema e IP) → bloqueado_ssrf; o destino proibido não recebe conexão."""
    alvo = quote(destino.format(p=liberado.porta), safe="")
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir-para?para={alvo}")))
    h1 = no(e, "h1")
    assert h1.status == "erro" and h1.erro_categoria == "bloqueado_ssrf", destino
    assert liberado.contagem("/secret") == 0


@pytest.mark.modulo("m3")
def test_host_vindo_de_placeholder_e_validado(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-02/PLH-04: host montado por placeholder (resposta do nó anterior) também passa pela validação de IP."""
    g = cadeia(cfg_http(f"{liberado.base}/valores"), cfg_http("http://{{ anterior.corpo.host }}/x"))
    _, e, _ = executar(cliente_coordenador, g)
    assert no(e, "h1").status == "sucesso"
    assert no(e, "h2").status == "erro" and no(e, "h2").erro_categoria == "bloqueado_ssrf"


@pytest.mark.modulo("m3")
def test_liberacao_e_so_do_host_porta_exato(cliente_coordenador, liberado, outro_servidor, executar, cadeia, cfg_http, no):
    """SEG-08: MOTOR_SSRF_LIBERAR é lista de 'host:porta' — outra porta no mesmo host continua bloqueada."""
    _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, outro_servidor, f"{outro_servidor.base}/ok")
    assert liberado.hits == []


@pytest.mark.modulo("m3")
def test_liberacao_vazia_por_padrao_em_todos_os_ambientes():
    """SEG-08: MOTOR_SSRF_LIBERAR existe e está vazia nas settings de teste (só fixture a altera)."""
    from django.conf import settings

    assert list(settings.MOTOR_SSRF_LIBERAR) == []


@pytest.mark.modulo("m3")
def test_servidor_local_nao_liberado_e_bloqueado_mesmo_com_dns_falso(cliente_coordenador, servidor, dns, executar, cadeia, cfg_http, no):
    """SEG-02: nome apontando para o servidor local sem liberação → bloqueado."""
    dns({"app.exemplo.test": ["127.0.0.1"]})
    _bloqueia(cliente_coordenador, executar, cadeia, cfg_http, no, servidor, f"http://app.exemplo.test:{servidor.porta}/ok")


@pytest.mark.modulo("m3")
def test_pin_do_ip_validado_e_host_original_no_cabecalho(cliente_coordenador, servidor, settings, dns, executar, cadeia, cfg_http, no):
    """SEG-04: valida num IP e conecta NESSE IP (anti DNS rebinding), enviando o Host original.

    Liberado 'rebind.exemplo.test:<porta>'; 1ª resolução → 127.0.0.1 (servidor local), as seguintes → 10.255.255.1 (inalcançável).
    Sem pin, o motor re-resolveria e iria a outro IP (travaria/falharia).
    """
    settings.MOTOR_SSRF_LIBERAR = [f"rebind.exemplo.test:{servidor.porta}"]
    dns({"rebind.exemplo.test": [["127.0.0.1"], ["10.255.255.1"]]}, sequencial=True)
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://rebind.exemplo.test:{servidor.porta}/eco")))
    assert e.status == "sucesso", no(e, "h1").erro_mensagem
    assert servidor.requisicoes[-1]["headers"]["host"] == f"rebind.exemplo.test:{servidor.porta}"


@pytest.mark.modulo("m3")
def test_redirect_valido_dentro_da_liberacao_funciona(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-05 (controle): redirect para destino permitido é seguido normalmente."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir-para?para={quote('/ok', safe='')}")))
    assert e.status == "sucesso" and no(e, "h1").saida["status"] == 200


@pytest.mark.modulo("m3")
def test_resolucao_sem_resultado_e_erro_dns_nao_ssrf(cliente_coordenador, servidor, dns, executar, cadeia, cfg_http, no):
    """SEG-10: nome que não resolve → categoria dns (não bloqueado_ssrf), sem conexão."""
    dns({"nao-existe.exemplo.test": None})
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://nao-existe.exemplo.test:{servidor.porta}/ok")))
    assert no(e, "h1").erro_categoria == "dns" and servidor.hits == []
    assert socket.gaierror is not None
