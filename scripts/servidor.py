#!/usr/bin/env python
"""Servidor central: um Postgres próprio desta máquina na porta 8081 + a aplicação na rede local.

  python scripts/servidor.py --ip 10.0.4.158 --porta 8001
  python scripts/servidor.py --importar-demo          # 1ª vez: copia o banco da demo (5433)
  python scripts/servidor.py --importar-demo --substituir   # recopia, apagando o central
  python scripts/servidor.py --so-banco               # só cria/liga o Postgres e sai

O cluster fica em ~/.construtor-workflows/pgcentral (localhost:8081, senha scram-sha-256).
Senhas, URL do banco e SECRET_KEY são gerados na 1ª vez e guardados em ~/.construtor-workflows/
(nunca impressos). O Postgres continua ligado ao parar a aplicação. Não semeia dados de demo.
Usa a mesma chave das Credenciais da demo, para que credenciais importadas continuem legíveis.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo  # noqa: E402  (define DJANGO_SETTINGS_MODULE=demo ao importar; trocado abaixo)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.servidor"  # forçado: nunca dev/.env

PASTA = Path.home() / ".construtor-workflows"
CLUSTER = PASTA / "pgcentral"
PORTA_BANCO = 8081
NOME_BANCO = "construtor"
USUARIO_BANCO = "construtor"
ARQUIVO_SUPERUSUARIO = PASTA / "pgcentral_superusuario"
ARQUIVO_URL = PASTA / "servidor_banco_url"
ARQUIVO_SECRET_KEY = PASTA / "servidor_secret_key"
ORIGEM_DEMO = {"host": "localhost", "port": "5433", "user": "postgres", "dbname": "construtor_demo"}


def _bin(nome):
    """Executável do Postgres: PG_BIN, PATH ou a instalação padrão do Windows (versão mais nova)."""
    if os.environ.get("PG_BIN"):
        return str(Path(os.environ["PG_BIN"]) / nome)
    if achado := shutil.which(nome):
        return achado
    pastas = Path("C:/Program Files/PostgreSQL").glob("*/bin")
    versao = lambda p: int(p.parent.name) if p.parent.name.isdigit() else 0  # noqa: E731
    for pasta in sorted(pastas, key=versao, reverse=True):
        if (pasta / f"{nome}.exe").exists():
            return str(pasta / f"{nome}.exe")
    raise SystemExit(f"AMBIENTE: não achei o {nome} do Postgres (defina PG_BIN).")


def _gravar_segredo(arquivo, valor):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(valor, encoding="utf-8")
    try:
        arquivo.chmod(0o600)
    except OSError:  # Windows: permissões POSIX não se aplicam
        pass


def _segredo(arquivo):
    if not arquivo.exists():
        _gravar_segredo(arquivo, secrets.token_urlsafe(32))
    return arquivo.read_text(encoding="utf-8").strip()


def _criar_cluster():
    """initdb na 1ª vez: UTF8/C (igual à demo), só localhost, senha obrigatória."""
    if (CLUSTER / "PG_VERSION").exists():
        return False
    senha = _segredo(ARQUIVO_SUPERUSUARIO)
    with tempfile.TemporaryDirectory() as tmp:
        pwfile = Path(tmp) / "pw"
        pwfile.write_text(senha, encoding="utf-8")
        subprocess.run(
            [_bin("initdb"), "-D", str(CLUSTER), "-U", "postgres", "-E", "UTF8", "--locale=C",
             "--auth=scram-sha-256", f"--pwfile={pwfile}"],
            check=True, stdout=subprocess.DEVNULL,
        )  # fmt: skip
    with (CLUSTER / "postgresql.conf").open("a", encoding="utf-8") as conf:
        conf.write(f"\n# Servidor central (scripts/servidor.py)\nport = {PORTA_BANCO}\n")
        conf.write("listen_addresses = 'localhost'\n")
    return True


def _ligar_cluster():
    """Sobe o Postgres desacoplado deste processo (continua ligado ao parar a aplicação).

    No Windows, o pg_ctl é criado pelo WMI (Win32_Process.Create): fica fora da árvore e do
    console de quem chamou, então Ctrl+C ou fechar o terminal não derrubam o banco.
    """
    status = subprocess.run([_bin("pg_ctl"), "status", "-D", str(CLUSTER)], capture_output=True)
    if status.returncode == 0:
        return False
    comando = [_bin("pg_ctl"), "start", "-D", str(CLUSTER), "-l", str(CLUSTER / "log.txt")]
    if os.name == "nt":
        linha = subprocess.list2cmdline(comando).replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
             f"-Arguments @{{CommandLine='{linha}'}} | Out-Null"],
            check=True,
        )  # fmt: skip
    else:
        subprocess.run(comando, check=True, stdout=subprocess.DEVNULL)
    for _ in range(120):
        pronto = subprocess.run(
            [_bin("pg_isready"), "-q", "-h", "localhost", "-p", str(PORTA_BANCO)]
        )
        if pronto.returncode == 0:
            return True
        time.sleep(1)
    raise SystemExit(f"AMBIENTE: o Postgres central não subiu; veja {CLUSTER / 'log.txt'}.")


def _conexao_super(dbname="postgres"):
    import psycopg

    return psycopg.connect(
        host="localhost", port=PORTA_BANCO, user="postgres", dbname=dbname, autocommit=True,
        password=ARQUIVO_SUPERUSUARIO.read_text(encoding="utf-8").strip(),
    )  # fmt: skip


def _criar_banco(substituir=False):
    """Papel `construtor` (sem superusuário) dono do banco `construtor`; grava a URL local."""
    if not ARQUIVO_URL.exists():
        senha = secrets.token_urlsafe(32)
        url = f"postgres://{USUARIO_BANCO}:{senha}@localhost:{PORTA_BANCO}/{NOME_BANCO}"
        _gravar_segredo(ARQUIVO_URL, url)
    senha = ARQUIVO_URL.read_text(encoding="utf-8").strip().split(":")[2].split("@")[0]
    with _conexao_super() as admin:
        existe = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (USUARIO_BANCO,))
        comando = "ALTER" if existe.fetchone() else "CREATE"
        admin.execute(f"{comando} ROLE {USUARIO_BANCO} LOGIN PASSWORD '{senha}'")
        if substituir:
            admin.execute(f'DROP DATABASE IF EXISTS "{NOME_BANCO}" WITH (FORCE)')
        achou = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (NOME_BANCO,))
        if achou.fetchone() is None:
            admin.execute(f'CREATE DATABASE "{NOME_BANCO}" OWNER {USUARIO_BANCO}')
    return senha


def _banco_vazio():
    with _conexao_super(NOME_BANCO) as conexao:
        tabela = conexao.execute("SELECT to_regclass('public.django_migrations')").fetchone()[0]
        return tabela is None


def _importar_demo(senha_app):
    """pg_dump do construtor_demo (5433) → pg_restore no central, com o dono `construtor`."""
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = Path(tmp) / "demo.dump"
        o = ORIGEM_DEMO
        subprocess.run(
            [_bin("pg_dump"), "-Fc", "-w", "-h", o["host"], "-p", o["port"], "-U", o["user"],
             "-d", o["dbname"], "-f", str(arquivo)],
            check=True,
        )  # fmt: skip
        subprocess.run(
            [_bin("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", "-w",
             "-h", "localhost", "-p", str(PORTA_BANCO), "-U", USUARIO_BANCO, "-d", NOME_BANCO,
             str(arquivo)],
            check=True, env={**os.environ, "PGPASSWORD": senha_app},
        )  # fmt: skip


def preparar_banco(importar=False, substituir=False):
    if _criar_cluster():
        print(f"Cluster criado em {CLUSTER} (porta {PORTA_BANCO}).")
    if _ligar_cluster():
        print(f"Postgres central ligado em localhost:{PORTA_BANCO}.")
    senha_app = _criar_banco(substituir=substituir and importar)
    _segredo(ARQUIVO_SECRET_KEY)
    if importar:
        if not _banco_vazio():
            raise SystemExit(
                "O banco central já tem dados; use --importar-demo --substituir para recopiar."
            )
        _importar_demo(senha_app)
        print("Banco da demo (construtor_demo, 5433) copiado para o central.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--porta", type=int, default=8001, help="porta da aplicação")
    parser.add_argument("--ip", help="também atende neste IP da rede local (escuta em 0.0.0.0)")
    parser.add_argument("--importar-demo", action="store_true", help="copia o construtor_demo")
    parser.add_argument("--substituir", action="store_true", help="com --importar-demo: recopia")
    parser.add_argument("--so-banco", action="store_true", help="só prepara o Postgres e sai")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    if args.ip:
        os.environ["SERVIDOR_IP"] = args.ip  # ALLOWED_HOSTS do settings.servidor (e do reloader)

    filho_do_reloader = os.environ.get("RUN_MAIN") == "true"
    if not filho_do_reloader:
        preparar_banco(importar=args.importar_demo, substituir=args.substituir)
        if args.so_banco:
            return 0
    demo._chave_local_de_demo()

    import django

    django.setup()
    from django.core.management import call_command

    if filho_do_reloader:
        demo._migrar_se_pendente(call_command)
    else:
        call_command("migrate", verbosity=0, interactive=False)
        demo._subir_worker("config.settings.servidor")
        print(f"\nBanco central: localhost:{PORTA_BANCO}/{NOME_BANCO}")
        print(f"Subindo em http://127.0.0.1:{args.porta}/  (Ctrl+C para parar)")
        if args.ip:
            print(f"Na rede: http://{args.ip}:{args.porta}/")
            print("  HTTP sem TLS: a senha do AD trafega aberta na rede.")
        print("O código recarrega sozinho ao salvar; migration nova é aplicada no reload.\n")
    endereco = "0.0.0.0" if args.ip else "127.0.0.1"
    call_command("runserver", f"{endereco}:{args.porta}", use_reloader=True, insecure_serving=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
