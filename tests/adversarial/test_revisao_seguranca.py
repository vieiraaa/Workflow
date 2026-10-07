"""T-030 · Revisão de segurança do M3 (Revisor de Segurança).

Testes VERMELHOS provam achados; os verdes registram o que foi verificado (inclui as lacunas do
aceite: json_invalido e timeout de conexão). Sem internet: servidores locais em 127.0.0.1
(liberados só via fixture `settings`, SEG-08) e DNS por monkeypatch.
"""

import gzip
import json
import socket
import threading
import time
import tracemalloc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from django.apps import apps
from django.urls import reverse

from apps.motor import http as motor_http

pytestmark = pytest.mark.modulo("m3")

SEGREDO = "segredo-ficticio-7f3a9"


# ---------------------------------------------------------------- servidores locais
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rotas = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.recebidas.append(self.path)
        for prefixo, tratar in self.rotas.items():
            if self.path.startswith(prefixo):
                return tratar(self)
        self._enviar(200, b'{"ok": true}', {"Content-Type": "application/json"})

    do_POST = do_GET

    def _enviar(self, status, corpo=b"", headers=None):
        self.send_response(status)
        for nome, valor in (headers or {}).items():
            self.send_header(nome, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


class _Servidor:
    def __init__(self, rotas):
        handler = type("H", (_Handler,), {"rotas": rotas})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.httpd.recebidas = []
        self.porta = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.porta}"

    def parar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _ServidorBruto:
    """Servidor TCP que responde com bytes crus, gotejando (slowloris do lado do servidor)."""

    def __init__(self, partes, intervalo, total_s):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.porta = self.sock.getsockname()[1]
        self.partes, self.intervalo, self.total_s = partes, intervalo, total_s
        self.parado = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.parado.is_set():
            try:
                conexao, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._atender, args=(conexao,), daemon=True).start()

    def _atender(self, conexao):
        try:
            conexao.recv(65536)
            fim = time.monotonic() + self.total_s
            for parte in self.partes:
                conexao.sendall(parte)
            while time.monotonic() < fim and not self.parado.is_set():
                conexao.sendall(b"X-Gota: 1\r\n")
                time.sleep(self.intervalo)
            conexao.sendall(b"Content-Length: 0\r\n\r\n")
        except OSError:
            pass
        finally:
            conexao.close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.porta}"

    def parar(self):
        self.parado.set()
        self.sock.close()


@pytest.fixture
def servidor_com():
    criados = []

    def _criar(rotas):
        s = _Servidor(rotas)
        criados.append(s)
        return s

    yield _criar
    for s in criados:
        s.parar()


@pytest.fixture
def limites_curtos(settings):
    settings.MOTOR_TIMEOUT_CONEXAO = 0.5
    settings.MOTOR_TIMEOUT_LEITURA = 0.5
    settings.MOTOR_TIMEOUT_NO = 1
    settings.MOTOR_TIMEOUT_EXECUCAO = 3
    return settings


# ---------------------------------------------------------------- grafo / execução
def _no(id_, tipo, config=None, x=0):
    return {
        "id": id_,
        "tipo": tipo,
        "titulo": id_.upper(),
        "posicao": {"x": x, "y": 0},
        "config": config or {},
    }


def _http(url, metodo="GET", headers=None, query=None, corpo=""):
    return {
        "metodo": metodo,
        "url": url,
        "headers": headers or [],
        "query": query or [],
        "corpo": corpo,
    }


def _cadeia(*configs):
    nos, ids = [_no("g", "gatilho")], ["g"]
    for i, c in enumerate(configs, 1):
        nos.append(_no(f"h{i}", "http", c, x=i * 100))
        ids.append(f"h{i}")
    nos.append(_no("s", "saida", x=900))
    ids.append("s")
    return {
        "versao": 1,
        "nos": nos,
        "arestas": [{"de": a, "para": b} for a, b in zip(ids, ids[1:], strict=False)],
    }


@pytest.fixture
def executar(fabrica_fluxo, cliente_adm):
    Execucao = apps.get_model("execucoes", "Execucao")

    def _exec(grafo):
        fluxo = fabrica_fluxo(grafo=grafo, status="ativo")
        r = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": fluxo.pk}))
        assert r.status_code == 302, r.status_code
        return Execucao.objects.filter(fluxo=fluxo).latest("pk")

    return _exec


def _no_exec(execucao, id_):
    return apps.get_model("execucoes", "ExecucaoNo").objects.get(execucao=execucao, no_id=id_)


# ================================================================ ACHADOS (vermelhos)
def test_headers_gotejados_nao_furam_o_prazo_do_no(limites_curtos):
    """ALTA · http.py:319 — `cliente.send(stream=True)` não tem prazo total: o timeout de leitura
    do httpx vale por operação de socket, então um servidor que goteja uma linha de header a cada
    0,2 s (< leitura 0,5 s) segura o worker indefinidamente, ignorando MOTOR_TIMEOUT_NO (1 s)."""
    srv = _ServidorBruto([b"HTTP/1.1 200 OK\r\n"], intervalo=0.2, total_s=4)
    limites_curtos.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    try:
        inicio = time.monotonic()
        with pytest.raises(motor_http.ErroHttp) as erro:
            motor_http.requisitar(metodo="GET", url=srv.base + "/")
        decorrido = time.monotonic() - inicio
    finally:
        srv.parar()
    assert erro.value.categoria == "timeout"
    assert decorrido < 2.0, f"prazo do nó (1 s) ignorado: {decorrido:.1f} s"


def test_cadeia_de_redirects_lentos_nao_fura_o_prazo_do_no(limites_curtos, servidor_com):
    """ALTA · http.py:350-366 — o prazo (`limite_tempo`) só é checado após ConnectError e entre
    pedaços do corpo; cada salto de redirect ganha connect+read cheios. 5 saltos de 0,4 s cada
    somam 2,4 s com MOTOR_TIMEOUT_NO=1 (em produção: 6 x 10 s = 60 s por nó, com prazo de 15 s)."""

    def lento(h):
        n = int(h.path.rsplit("/", 1)[1])
        time.sleep(0.4)
        if n < 5:
            return h._enviar(302, headers={"Location": f"/r/{n + 1}"})
        return h._enviar(200, b"fim")

    srv = servidor_com({"/r/": lento})
    limites_curtos.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    inicio = time.monotonic()
    with pytest.raises(motor_http.ErroHttp) as erro:
        motor_http.requisitar(metodo="GET", url=srv.base + "/r/0")
    decorrido = time.monotonic() - inicio
    assert erro.value.categoria == "timeout"
    assert decorrido < 1.8


def test_bomba_gzip_nao_explode_memoria(settings, servidor_com):
    """MÉDIA · http.py:244 — `iter_bytes()` descompacta cada pedaço de rede inteiro (zlib sem
    max_length) ANTES de checar o limite: ~64 KB de gzip viram ~64 MB em memória de uma vez,
    embora MOTOR_LIMITE_RESPOSTA seja 1 MB. Vários nós/execuções simultâneas = DoS de memória."""
    bomba = gzip.compress(b"\0" * (200 * 1024 * 1024), compresslevel=9)

    def rota(h):
        h._enviar(200, bomba, {"Content-Encoding": "gzip", "Content-Type": "text/plain"})

    srv = servidor_com({"/bomba": rota})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    tracemalloc.start()
    try:
        resposta = motor_http.requisitar(metodo="GET", url=srv.base + "/bomba")
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert resposta["truncado"] is True
    assert pico < 16 * 1024 * 1024, f"pico de memória {pico / 2**20:.0f} MB para limite de 1 MB"


def test_segredo_de_set_cookie_vaza_no_historico_via_placeholder(
    db, servidor_com, settings, executar
):
    """MÉDIA · executor.py:168/184 + mascarar.py:22 — o nó seguinte recebe a saída BRUTA (sem
    máscara) e a entrada gravada só é mascarada pelo NOME do par. `{{ anterior.headers.set-cookie }}`
    num parâmetro `q` grava o cookie de sessão em claro no histórico (SEG-09), visível no detalhe."""

    def login(h):
        h._enviar(
            200, b"{}", {"Set-Cookie": f"sessao={SEGREDO}", "Content-Type": "application/json"}
        )

    srv = servidor_com({"/login": login})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    grafo = _cadeia(
        _http(srv.base + "/login"),
        _http(
            srv.base + "/eco", query=[{"nome": "q", "valor": "{{ anterior.headers.set-cookie }}"}]
        ),
    )
    execucao = executar(grafo)
    assert _no_exec(execucao, "h1").saida["headers"]["set-cookie"] == "••••"
    assert SEGREDO not in json.dumps(_no_exec(execucao, "h2").entrada, ensure_ascii=False)


def test_snapshot_nao_mascara_header_com_nome_vindo_de_placeholder(
    db, servidor_com, settings, executar
):
    """BAIXA · mascarar.py:64-70 — `mascarar_grafo` decide pelo nome LITERAL; header com nome
    `{{anterior.corpo.h}}` (resolve para Authorization) grava o valor em claro no grafo_snapshot,
    embora a entrada do nó saia mascarada (SEG-16.5)."""

    def nome(h):
        h._enviar(200, b'{"h": "Authorization"}', {"Content-Type": "application/json"})

    srv = servidor_com({"/nome": nome})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    grafo = _cadeia(
        _http(srv.base + "/nome"),
        _http(
            srv.base + "/x",
            headers=[{"nome": "{{anterior.corpo.h}}", "valor": f"Bearer {SEGREDO}"}],
        ),
    )
    execucao = executar(grafo)
    assert SEGREDO not in json.dumps(_no_exec(execucao, "h2").entrada, ensure_ascii=False)
    assert SEGREDO not in json.dumps(execucao.grafo_snapshot, ensure_ascii=False)


def test_query_sensivel_percent_encoded_na_url_nao_e_mascarada(
    db, servidor_com, settings, executar
):
    """BAIXA · mascarar.py:14/35 — `mascarar_url` compara o nome cru: `?api%5Fkey=` chega ao
    servidor como `api_key` mas fica em claro na entrada e no snapshot."""
    srv = servidor_com({})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    execucao = executar(_cadeia(_http(srv.base + f"/x?api%5Fkey={SEGREDO}")))
    assert srv.httpd.recebidas, "requisição não chegou"
    assert SEGREDO not in json.dumps(_no_exec(execucao, "h1").entrada, ensure_ascii=False)
    assert SEGREDO not in json.dumps(execucao.grafo_snapshot, ensure_ascii=False)


def test_surrogate_na_resposta_nao_derruba_a_execucao(
    db, servidor_com, settings, fabrica_fluxo, cliente_adm
):
    """MÉDIA · executor.py:139-152/198 + mascarar.py:56 — um servidor remoto que responde
    `{"x": "\\ud800"}` (surrogate solto, aceito pelo json.loads) faz o Postgres recusar o jsonb da
    `saida` no `_gravar`, que está FORA do try: 500 em fluxos:executar e a Execucao fica presa em
    `executando` (sem nós gravados). Qualquer destino externo derruba a execução de qualquer fluxo."""
    Execucao = apps.get_model("execucoes", "Execucao")

    def surrogate(h):
        h._enviar(200, b'{"x": "\\ud800"}', {"Content-Type": "application/json"})

    srv = servidor_com({"/s": surrogate})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    fluxo = fabrica_fluxo(grafo=_cadeia(_http(srv.base + "/s")), status="ativo")
    cliente_adm.raise_request_exception = False
    r = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": fluxo.pk}))
    assert r.status_code == 302, f"fluxos:executar respondeu {r.status_code}"
    execucao = Execucao.objects.filter(fluxo=fluxo).latest("pk")
    assert execucao.status in ("sucesso", "erro")


# ================================================================ VERIFICADO (verdes)
@pytest.mark.parametrize(
    "url",
    [
        "HTTP://127.0.0.1/",
        "hTTp://[::1]/",
        "http://2130706433/",
        "http://0177.0.0.1/",
        "http://0x7f.1/",
        "http://127.1/",
        "http://0x7f000001/",
        "http://017700000001/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:7f00:1]/",
        "http://[::127.0.0.1]/",
        "http://[64:ff9b::a9fe:a9fe]/",
        "http://[2002:a9fe:a9fe::]/",
        "http://[fd00:ec2::254]/",
        "http://[fe80::1%25en0]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0/",
        "http://[::]/",
        "http://100.64.0.1/",
        "http://localhost./",
        "http://LOCALHOST/",
        "http://x.localhost/",
        "http://evil.test@127.0.0.1/",
        "http://127.0.0.1#@evil.test/",
        "http://127.0.0.1\\@evil.test/",
        "http://127.0.0.1%09/",
        "file:///etc/passwd",
        "gopher://127.0.0.1:70/",
        "FTP://127.0.0.1/",
        "http://ⓛⓞⓒⓐⓛⓗⓞⓢⓣ/",
    ],
)
def test_ssrf_formas_alternativas_bloqueadas(url, settings, monkeypatch):
    settings.MOTOR_SSRF_LIBERAR = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",  # nenhum nome sai para a rede
        lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p))],
    )
    with pytest.raises(motor_http.ErroHttp) as erro:
        motor_http.requisitar(metodo="GET", url=url)
    assert erro.value.categoria in ("bloqueado_ssrf", "dns")
    assert "127.0.0.1" not in erro.value.mensagem


def test_ssrf_dns_com_qualquer_ip_proibido_bloqueia_sem_conectar(settings, monkeypatch):
    def falso(host, porta, *a, **k):
        assert host == "misto.test"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", porta)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:10.0.0.1", porta, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", falso)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("conectou"))
    with pytest.raises(motor_http.ErroHttp) as erro:
        motor_http.requisitar(metodo="GET", url="http://misto.test/")
    assert erro.value.categoria == "bloqueado_ssrf"


def test_redirect_para_loopback_e_para_file_bloqueados(settings, servidor_com):
    srv = servidor_com(
        {
            "/meta": lambda h: h._enviar(302, headers={"Location": "http://169.254.169.254/"}),
            "/file": lambda h: h._enviar(302, headers={"Location": "file:///etc/passwd"}),
            "/rel": lambda h: h._enviar(302, headers={"Location": "//[::1]:1/"}),
        }
    )
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    for caminho in ("/meta", "/file", "/rel"):
        with pytest.raises(motor_http.ErroHttp) as erro:
            motor_http.requisitar(metodo="GET", url=srv.base + caminho)
        assert erro.value.categoria == "bloqueado_ssrf", caminho


def test_timeout_de_conexao_vira_categoria_timeout(settings, monkeypatch):
    """Lacuna do aceite: ConnectTimeout → `timeout`, mensagem própria, sem texto do driver."""
    settings.MOTOR_SSRF_LIBERAR = ["conecta.test:80"]
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p))],
    )

    def estoura(self, request):
        raise httpx.ConnectTimeout("timed out connecting to 127.0.0.1:80 SEGREDO-DRIVER")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", estoura)
    with pytest.raises(motor_http.ErroHttp) as erro:
        motor_http.requisitar(metodo="GET", url="http://conecta.test/")
    assert erro.value.categoria == "timeout"
    assert erro.value.mensagem == motor_http.MENSAGENS["timeout"]


def test_json_invalido_no_envio_nao_dispara_requisicao(
    db, servidor_com, settings, executar, monkeypatch
):
    """Lacuna do aceite (SEG-16.4): corpo resolvido inválido → json_invalido, nada enviado.
    O editor só deixa salvar JSON válido e o placeholder escapa como string; forçamos o caso
    defensivo trocando o resolvedor do corpo."""
    from apps.motor import placeholders

    srv = servidor_com({})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    monkeypatch.setattr(placeholders, "resolver_corpo", lambda texto, anterior: '{"a": ')
    execucao = executar(_cadeia(_http(srv.base + "/x", metodo="POST", corpo='{"a": 1}')))
    h1 = _no_exec(execucao, "h1")
    assert h1.erro_categoria == "json_invalido"
    assert srv.httpd.recebidas == []


def test_crlf_de_placeholder_em_header_nao_envia(db, servidor_com, settings, executar):
    srv = servidor_com(
        {
            "/crlf": lambda h: h._enviar(
                200, b'{"v": "a\\r\\nX-Injetado: 1"}', {"Content-Type": "application/json"}
            )
        }
    )
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    execucao = executar(
        _cadeia(
            _http(srv.base + "/crlf"),
            _http(srv.base + "/alvo", headers=[{"nome": "X-V", "valor": "{{ anterior.corpo.v }}"}]),
        )
    )
    assert _no_exec(execucao, "h2").erro_categoria == "placeholder"
    assert not any(p.startswith("/alvo") for p in srv.httpd.recebidas)


def test_base_nao_ve_execucao_alheia(db, servidor_com, settings, executar, cliente_base):
    srv = servidor_com({})
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{srv.porta}"]
    execucao = executar(_cadeia(_http(srv.base + "/x")))
    r = cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}))
    assert r.status_code == 404
    assert (
        cliente_base.get(reverse("execucoes:lista")).content.count(
            reverse("execucoes:detalhe", kwargs={"pk": execucao.pk}).encode()
        )
        == 0
    )
