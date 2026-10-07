import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest


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
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b""
        partes = urlsplit(self.path)
        estado = self.server.estado
        estado.requisicoes.append(
            {
                "metodo": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "corpo": corpo.decode("utf-8", "replace"),
            }
        )
        json_h = {"Content-Type": "application/json"}
        caminho = partes.path
        if caminho == "/ok":
            self._enviar(200, b'{"ok": true}', json_h)
        elif caminho == "/valores":
            self._enviar(200, json.dumps({"crlf": "a\r\nInjetado: 1", "v": "x"}).encode(), json_h)
        elif caminho == "/eco":
            self._enviar(200, json.dumps(estado.requisicoes[-1]).encode(), json_h)
        elif caminho == "/texto":
            self._enviar(200, b"nao e json", {"Content-Type": "text/plain; charset=utf-8"})
        elif caminho == "/latin1":
            self._enviar(
                200, "ação".encode("latin-1"), {"Content-Type": "text/plain; charset=latin-1"}
            )
        elif caminho == "/json-ruim":
            self._enviar(200, b"{nao json", json_h)
        elif caminho == "/nan":
            self._enviar(200, b'{"x": NaN}', json_h)
        elif caminho.startswith("/status/"):
            self._enviar(int(caminho.rsplit("/", 1)[1]), b'{"erro": "x"}', json_h)
        elif caminho == "/cabecalhos":
            self._enviar(
                200,
                b"{}",
                {**json_h, "Set-Cookie": "a=1", "X-Api-Key": "k", "X-Publico": "visivel"},
            )
        elif caminho == "/grande":
            self._enviar(200, b"x" * (1536 * 1024), {"Content-Type": "text/plain"})
        elif caminho == "/exato":
            self._enviar(200, b"y" * 1024, {"Content-Type": "text/plain"})
        elif caminho == "/gzip":
            self._enviar(
                200,
                gzip.compress(b"0" * (6 * 1024 * 1024)),
                {"Content-Type": "text/plain", "Content-Encoding": "gzip"},
            )
        elif caminho == "/lento":
            time.sleep(2)
            self._enviar(200, b"{}", json_h)
        elif caminho.startswith("/redir/"):
            restantes = int(caminho.rsplit("/", 1)[1])
            destino = "/ok" if restantes <= 1 else f"/redir/{restantes - 1}"
            self._enviar(302, b"", {"Location": destino})
        elif caminho == "/redir-para":
            self._enviar(
                self.server.estado.codigo_redirect,
                b"",
                {"Location": parse_qs(partes.query)["para"][0]},
            )
        elif caminho == "/redir-sem-location":
            self._enviar(302, b"semlocation", {"Content-Type": "text/plain"})
        else:
            self._enviar(404, b"nao encontrado", {"Content-Type": "text/plain"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _tratar


class ServidorLocal:
    def __init__(self):
        self.requisicoes = []
        self.codigo_redirect = 302
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.estado = self
        self.porta = self._httpd.server_address[1]
        threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.porta}"

    @property
    def caminhos(self):
        return [r["path"] for r in self.requisicoes]

    def parar(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def servidor():
    s = ServidorLocal()
    yield s
    s.parar()


@pytest.fixture
def liberado(servidor, settings):
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{servidor.porta}"]
    return servidor


@pytest.fixture
def dns(monkeypatch):
    """dns({'nome': ['ip', ...] | None}, sequencial=False) — só para os nomes dados."""
    import socket

    original = socket.getaddrinfo
    chamadas = {}

    def instalar(mapa, sequencial=False):
        def falso(host, porta, *args, **kwargs):
            if host not in mapa:
                return original(host, porta, *args, **kwargs)
            chamadas[host] = chamadas.get(host, 0) + 1
            destino = mapa[host]
            if destino is None:
                raise socket.gaierror(socket.EAI_NONAME, "nao existe")
            if sequencial:
                destino = destino[min(chamadas[host], len(destino)) - 1]
            return [
                (
                    socket.AF_INET6 if ":" in ip else socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (ip, porta or 0, 0, 0) if ":" in ip else (ip, porta or 0),
                )
                for ip in destino
            ]

        monkeypatch.setattr(socket, "getaddrinfo", falso)
        return chamadas

    return instalar
