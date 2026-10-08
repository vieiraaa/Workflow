"""Monitor do servidor de demo: mostra se está ATIVO ou INATIVO e registra cada ativação/queda.

Uso: python docs/ferramentas/monitor_servidor.py [--url URL] [--intervalo 3]
(URL padrão: http://127.0.0.1:8000/entrar/)
Só biblioteca padrão; portável (macOS/Windows). Não lê .env nem toca o banco.
"""

import argparse
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

VERDE, VERMELHO, AMARELO, CINZA, NEGRITO, FIM = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[90m",
    "\033[1m",
    "\033[0m",
)


def sondar(url, timeout=2.0):
    """Devolve (ativo, status_http, ms)."""
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - URL local fixa
            return True, resp.status, (time.perf_counter() - inicio) * 1000
    except urllib.error.HTTPError as erro:
        # Respondeu com erro HTTP: o servidor está no ar.
        return True, erro.code, (time.perf_counter() - inicio) * 1000
    except urllib.error.URLError, TimeoutError, ConnectionError, OSError:
        return False, None, None


def porta_aberta(url, timeout=1.0):
    """Checagem leve por TCP (não aparece no log do servidor)."""
    parte = urllib.parse.urlsplit(url)
    try:
        with socket.create_connection((parte.hostname, parte.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


def duracao(segundos):
    m, s = divmod(int(segundos), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}min {s:02d}s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/entrar/")
    ap.add_argument("--intervalo", type=float, default=3.0)
    ap.add_argument("--http-a-cada", type=float, default=60.0, help="segundos entre checagens HTTP")
    args = ap.parse_args()

    titulo = f"{NEGRITO}Monitor do servidor de demo{FIM}"
    print(f"{titulo}  {CINZA}{args.url} · a cada {args.intervalo:g}s{FIM}")
    print(f"{CINZA}Ativações e quedas ficam abaixo; a última linha é o estado atual.{FIM}\n")
    estado, desde, ativacoes = None, time.time(), 0
    status, ms, ultima_http = None, None, 0.0
    while True:
        ativo = porta_aberta(args.url)
        if ativo and (estado is not True or time.time() - ultima_http >= args.http_a_cada):
            ativo, status, ms = sondar(args.url)
            ultima_http = time.time()
        agora = datetime.now().strftime("%H:%M:%S")
        if ativo != estado:
            if estado is not None:
                print("\r\033[K", end="")
            if ativo:
                ativacoes += 1
                print(f"{VERDE}▲ {agora}  ATIVADO{FIM}  (ativação nº {ativacoes})")
            else:
                tempo = f" após {duracao(time.time() - desde)} no ar" if estado else ""
                print(f"{VERMELHO}▼ {agora}  INATIVO{FIM}{tempo}")
            estado, desde = ativo, time.time()
        if ativo:
            cor = VERDE if status and status < 500 else AMARELO
            linha = (
                f"{cor}● ATIVO{FIM}  {agora}  último HTTP {status} ({ms:.0f} ms)  "
                f"no ar há {duracao(time.time() - desde)}  ativações: {ativacoes}"
            )
        else:
            parado = duracao(time.time() - desde)
            linha = f"{VERMELHO}● INATIVO{FIM}  {agora}  sem resposta há {parado}"
        print("\r\033[K" + linha, end="", flush=True)
        time.sleep(args.intervalo)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
