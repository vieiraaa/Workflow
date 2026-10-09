"""T-059: segunda parede de rede do nó Código (SEG-20). Só servidor local, sem internet."""

import os
import statistics
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from apps.motor.codigo import executor, isolamento
from apps.motor.codigo.executor import CodigoErro, executar_codigo

pytestmark = pytest.mark.modulo("m5")
sem_camada = pytest.mark.skipif(
    not isolamento.disponivel(), reason="sem camada de rede do SO nesta máquina"
)


class _Servidor:
    def __init__(self):
        self.recebidas = []
        servidor = self

        class Tratador(BaseHTTPRequestHandler):
            def do_GET(self):
                servidor.recebidas.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Tratador)
        self.porta = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def parar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servidor():
    s = _Servidor()
    yield s
    s.parar()


def _ataque(tmp_path):
    script = tmp_path / "ataque.cjs"
    script.write_text(
        "const net = require('net');\n"
        "const s = net.connect(Number(process.argv[2]), '127.0.0.1', () => "
        "s.write('GET /vazou HTTP/1.0\\r\\n\\r\\n'));\n"
        "s.on('data', () => { s.end(); process.exit(0); });\n"
        "s.on('error', () => process.exit(3));\n"
        "setTimeout(() => process.exit(4), 2000);\n"
    )
    return os.path.realpath(script)


def _flags(raiz):
    return ["--permission", f"--allow-fs-read={raiz}", "--disallow-code-generation-from-strings"]


def test_controle_sem_a_camada_o_node_conecta(servidor, tmp_path):
    """Prova que o ataque é válido: o `--permission` sozinho NÃO barra rede (achado da T-058)."""
    node = isolamento.node_real()
    if node is None:
        pytest.skip("Node.js ausente")
    raiz = os.path.realpath(tmp_path)
    subprocess.run([node, *_flags(raiz), _ataque(tmp_path), str(servidor.porta)], env={}, timeout=8)
    assert servidor.recebidas == ["/vazou"]


@sem_camada
def test_na_camada_o_node_nao_conecta(servidor, tmp_path):
    raiz = os.path.realpath(tmp_path)
    argv = isolamento.comando([isolamento.node_real(), *_flags(raiz), _ataque(tmp_path)])
    resultado = subprocess.run([*argv, str(servidor.porta)], env={}, timeout=8, check=False)
    time.sleep(0.2)
    assert servidor.recebidas == [] and resultado.returncode != 0


@sem_camada
def test_lancador_de_testes_executa_node_dentro_da_camada(servidor, tmp_path):
    lancador = isolamento.criar_lancador(tmp_path)
    assert lancador and os.access(lancador, os.X_OK)
    raiz = os.path.realpath(tmp_path)
    subprocess.run(
        [lancador, *_flags(raiz), _ataque(tmp_path), str(servidor.porta)], env={}, timeout=8
    )
    assert servidor.recebidas == []


@sem_camada
def test_o_runner_funciona_dentro_da_camada():
    saida = executar_codigo("return [{json: {ok: 1 + 1}}];", [])
    assert saida["itens"] == [{"json": {"ok": 2}}]


def test_sem_camada_o_no_codigo_nao_roda_falha_fechada(monkeypatch):
    monkeypatch.setattr(isolamento, "camada", lambda: None)
    with pytest.raises(CodigoErro) as erro:
        executar_codigo("return [{json: {}}];", [])
    assert erro.value.categoria == "codigo_indisponivel"
    assert erro.value.mensagem == isolamento.MSG_INDISPONIVEL
    assert isolamento.comando(["x"]) is None and isolamento.criar_lancador() is None


def test_nao_ha_como_desligar_a_camada_por_ambiente(monkeypatch):
    """NODE_BIN e afins não contornam a parede: o executor sempre envolve o node pela camada."""
    monkeypatch.setattr(isolamento, "camada", lambda: None)
    monkeypatch.setenv("NODE_BIN", isolamento.node_real() or "node")
    monkeypatch.setenv("NODE_ISOLADO", "0")
    with pytest.raises(CodigoErro) as erro:
        executar_codigo("return [{json: {}}];", [])
    assert erro.value.categoria == "codigo_indisponivel"


@sem_camada
def test_comando_do_runner_vem_envolvido_pela_camada():
    argv = executor._comando()
    nome, prefixo = isolamento.camada()
    assert argv[: len(prefixo)] == list(prefixo) and "--permission" in argv


@sem_camada
def test_custo_de_partida_com_a_camada():
    """Medida de referência (não é limite rígido): partida do runner com e sem a camada."""

    def mediana(f):
        tempos = []
        for _ in range(7):
            t = time.monotonic()
            f()
            tempos.append((time.monotonic() - t) * 1000)
        return statistics.median(tempos)

    com = mediana(lambda: executar_codigo("return [{json: {}}];", []))
    node = isolamento.node_real()
    sem = mediana(lambda: subprocess.run([node, "-e", "0"], env={}, capture_output=True))
    print(f"partida do runner: com camada {com:.0f} ms; node puro {sem:.0f} ms")
    assert com < 3000
