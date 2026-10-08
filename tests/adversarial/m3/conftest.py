"""Fixtures do adversarial M3 (cópia independente do aceite, com rotas hostis extras): servidor HTTP LOCAL em thread (nunca internet) e atalhos de execução.

SUPOSIÇÕES (lacunas registradas no relatório): models `execucoes.Execucao` e `execucoes.ExecucaoNo` com os campos
de estados.yaml (SEG-16.1); MOTOR_SSRF_LIBERAR = lista de "host-literal:porta" (SEG-08/SEG-16.2), alterada só aqui via a fixture `settings`.
"""

import copy
import gzip
import json
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from django.apps import apps
from django.urls import reverse


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _enviar(self, status, corpo=b"", headers=None):
        self.send_response(status)
        for nome, valor in (headers or {}).items():
            self.send_header(nome, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(corpo)

    def _tratar(self):
        servidor = self.server.estado
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b""
        partes = urlsplit(self.path)
        servidor.hits.append((self.command, self.path))
        servidor.requisicoes.append(
            {"metodo": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "corpo": corpo.decode("utf-8", "replace")}
        )
        caminho = partes.path
        json_h = {"Content-Type": "application/json"}
        if caminho == "/ok":
            self._enviar(200, json.dumps({"ok": True, "n": 1}).encode(), json_h)
        elif caminho.startswith("/status/"):
            codigo = int(caminho.rsplit("/", 1)[1])
            self._enviar(codigo, json.dumps({"erro": "detalhe do servidor", "codigo": codigo}).encode(), json_h)
        elif caminho.startswith("/eco"):
            resposta = {
                "metodo": self.command,
                "path": self.path,
                "query": parse_qs(partes.query),
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "corpo": corpo.decode("utf-8", "replace"),
            }
            self._enviar(200, json.dumps(resposta).encode(), json_h)
        elif caminho == "/valores":
            valores = {
                "v": 'a/b?c#d@e f"g\\h',
                "lista": [10, 20, 30],
                "obj": {"k": [1, 2]},
                "crlf": "a\r\nInjetado: 1",
                "host": "169.254.169.254",
                "num": 7,
            }
            self._enviar(200, json.dumps(valores).encode(), {**json_h, "X-Marcador": "ABC"})
        elif caminho == "/alvo":
            self._enviar(200, json.dumps({"v": parse_qs(partes.query).get("v", [""])[0]}).encode(), json_h)
        elif caminho == "/infinito":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            bloco = b"y" * 65536
            try:
                for _ in range(400):
                    self.wfile.write(f"{len(bloco):x}\r\n".encode() + bloco + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.01)
            except OSError:
                pass
        elif caminho == "/gotejar":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b"z")
                    self.wfile.flush()
                    time.sleep(0.3)
            except OSError:
                pass
        elif caminho == "/muitos-headers":
            self._enviar(200, b"{}", {**json_h, **{f"X-H{i}": f"v{i}" for i in range(300)}})
        elif caminho == "/header-enorme":
            self._enviar(200, b"{}", {**json_h, "X-Enorme": "h" * 70000})
        elif caminho == "/gzip-bomba":
            comp = zlib.compressobj(9, zlib.DEFLATED, 31)
            bloco = b"\0" * (1024 * 1024)
            dados = b"".join(comp.compress(bloco) for _ in range(300)) + comp.flush()
            self._enviar(200, dados, {"Content-Type": "text/plain", "Content-Encoding": "gzip"})
        elif caminho == "/enorme":
            self._enviar(200, json.dumps({"v": "x" * 900000}).encode(), json_h)
        elif caminho == "/redir-self":
            self._enviar(302, b"", {"Location": "/redir-self"})
        elif caminho == "/nul":
            self._enviar(200, b"antes\x00depois", {"Content-Type": "application/octet-stream"})
        elif caminho == "/profundo":
            self._enviar(200, ("[" * 100000 + "]" * 100000).encode(), json_h)
        elif caminho == "/chave-ponto":
            self._enviar(200, json.dumps({"a.b": 1, "a": {"b": 2}, "__proto__": 3}).encode(), json_h)
        elif caminho == "/xss-completo":
            evil = "<img src=x onerror=window.__pwn=1><script>window.__pwn=1</script>"
            self._enviar(
                200,
                json.dumps({evil: evil, "lista": [evil], "texto": "</script><script>window.__pwn=1</script>"}).encode(),
                {**json_h, "X-Evil": evil, "X-Outro": "\"><svg/onload=window.__pwn=1>"},
            )
        elif caminho == "/texto":
            self._enviar(200, b"texto simples, nao json", {"Content-Type": "text/plain; charset=utf-8"})
        elif caminho == "/xss":
            self._enviar(200, b"<script>window.__pwn=1</script><img src=x onerror=window.__pwn=1>", {"Content-Type": "text/html"})
        elif caminho == "/cabecalhos":
            self._enviar(
                200,
                json.dumps({"ok": True}).encode(),
                {**json_h, "Set-Cookie": "sessao=SEGREDO-COOKIE-RESP", "X-Api-Key": "SEGREDO-APIKEY-RESP", "X-Token-Interno": "SEGREDO-TOKEN-RESP", "X-Publico": "visivel"},
            )
        elif caminho == "/grande":
            self._enviar(200, b"x" * (1536 * 1024), {"Content-Type": "text/plain"})
        elif caminho == "/gzip":
            self._enviar(200, gzip.compress(b"0" * (6 * 1024 * 1024)), {"Content-Type": "text/plain", "Content-Encoding": "gzip"})
        elif caminho == "/lento":
            time.sleep(float(parse_qs(partes.query).get("s", ["3"])[0]))
            self._enviar(200, b"{}", json_h)
        elif caminho.startswith("/redir/"):
            restantes = int(caminho.rsplit("/", 1)[1])
            destino = "/ok" if restantes <= 1 else f"/redir/{restantes - 1}"
            self._enviar(302, b"", {"Location": destino})
        elif caminho == "/redir-para":
            destino = parse_qs(partes.query)["para"][0]
            self._enviar(302, b"", {"Location": destino})
        else:
            self._enviar(404, b"nao encontrado", {"Content-Type": "text/plain"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _tratar


class ServidorLocal:
    def __init__(self):
        self.hits = []
        self.requisicoes = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.block_on_close = False
        self._httpd.estado = self
        self.porta = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.porta}"

    def contagem(self, prefixo):
        return sum(1 for _, p in self.hits if p.startswith(prefixo))

    def parar(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def servidor():
    """Servidor HTTP local (127.0.0.1, porta efêmera). NÃO liberado: o motor real o bloqueia (SEG-02)."""
    s = ServidorLocal()
    yield s
    s.parar()


@pytest.fixture
def outro_servidor():
    """Segundo servidor local (outra porta), nunca liberado."""
    s = ServidorLocal()
    yield s
    s.parar()


@pytest.fixture
def liberado(servidor, settings):
    """SEG-08: libera só este servidor de teste via settings.MOTOR_SSRF_LIBERAR."""
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{servidor.porta}"]
    return servidor


def _no(id_, tipo, config=None, x=0):
    return {"id": id_, "tipo": tipo, "titulo": id_.upper(), "posicao": {"x": x, "y": 0}, "config": config or {}}


def _cfg_http(url, metodo="GET", headers=None, query=None, corpo=""):
    return {"metodo": metodo, "url": url, "headers": headers or [], "query": query or [], "corpo": corpo}


def _cadeia(*configs_http):
    """gatilho → http1 → http2 … → saida (ids g, h1.., s)."""
    nos = [_no("g", "gatilho")]
    ids = ["g"]
    for i, c in enumerate(configs_http, 1):
        nos.append(_no(f"h{i}", "http", c, x=i * 100))
        ids.append(f"h{i}")
    nos.append(_no("s", "saida", x=900))
    ids.append("s")
    return {"versao": 1, "nos": nos, "arestas": [{"de": a, "para": b} for a, b in zip(ids, ids[1:], strict=False)]}


@pytest.fixture
def cfg_http():
    """cfg_http(url, metodo, headers, query, corpo) → config de nó http."""
    return _cfg_http


@pytest.fixture
def cadeia():
    """cadeia(cfg1, cfg2…) → grafo gatilho → http… → saída (ids g, h1.., s)."""
    return _cadeia


@pytest.fixture
def modelos():
    class M:
        Execucao = apps.get_model("execucoes", "Execucao")
        ExecucaoNo = apps.get_model("execucoes", "ExecucaoNo")
        Fluxo = apps.get_model("fluxos", "Fluxo")

    return M


@pytest.fixture
def executar(fabrica_fluxo, modelos):
    """Cria um fluxo ativo com o grafo e executa via POST fluxos:executar. Devolve (resposta, execucao|None, fluxo)."""

    def _exec(cliente, grafo, status="ativo", follow=False, fluxo=None):
        f = fluxo or fabrica_fluxo(grafo=copy.deepcopy(grafo), status=status)
        antes = set(modelos.Execucao.objects.values_list("pk", flat=True))
        r = cliente.post(reverse("fluxos:executar", kwargs={"pk": f.pk}), follow=follow)
        novas = modelos.Execucao.objects.exclude(pk__in=antes).order_by("pk")
        return r, novas.last(), f

    return _exec


@pytest.fixture
def nos_de(modelos):
    def _nos(execucao):
        return list(modelos.ExecucaoNo.objects.filter(execucao=execucao).order_by("ordem"))

    return _nos


@pytest.fixture
def no(modelos):
    """no(execucao, 'h1') → ExecucaoNo daquele nó do grafo."""

    def _no_de(execucao, id_):
        return modelos.ExecucaoNo.objects.get(execucao=execucao, no_id=id_)

    return _no_de


@pytest.fixture
def dns(monkeypatch):
    """dns({'nome': ['ip1', 'ip2']}) ou dns({'nome': [['ip_1a_chamada'], ['ip_2a_chamada']]}, sequencial=True).

    Substitui socket.getaddrinfo só para os nomes dados (sem rede externa). Nomes → `socket.gaierror` com None.
    Devolve o contador de chamadas por nome.
    """
    import socket

    original = socket.getaddrinfo
    chamadas = {}

    def instalar(mapa, sequencial=False):
        def falso(host, porta, *args, **kwargs):
            if host in mapa:
                chamadas[host] = chamadas.get(host, 0) + 1
                destino = mapa[host]
                if destino is None:
                    raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
                if sequencial:
                    destino = destino[min(chamadas[host], len(destino)) - 1]
                resultado = []
                for ip in destino:
                    familia = socket.AF_INET6 if ":" in ip else socket.AF_INET
                    endereco = (ip, porta or 0, 0, 0) if familia == socket.AF_INET6 else (ip, porta or 0)
                    resultado.append((familia, socket.SOCK_STREAM, 6, "", endereco))
                return resultado
            return original(host, porta, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", falso)
        return chamadas

    return instalar
