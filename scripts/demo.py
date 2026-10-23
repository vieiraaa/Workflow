#!/usr/bin/env python
"""Servidor de demonstração local, só com dados fictícios.

  python scripts/demo.py              # cria o banco local se faltar, migra, semeia e sobe em :8000
  python scripts/demo.py --porta 8010
  python scripts/demo.py --resetar    # apaga e recria o banco de demo

Usa config.settings.demo: Postgres local (construtor_demo), nunca o .env nem o Supabase.
Sobe também o worker do cadastro de processos (manage.py processar_cadastros). Sem
CREDENCIAIS_CHAVE no ambiente, usa a chave LOCAL de demo (~/.construtor-workflows/
demo_credenciais_chave, criada se faltar; nunca a do .env).
"""

import argparse
import atexit
import io
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.demo"  # forçado: nunca dev/.env

SENHA_DEMO = "Demo-Senha-Local-2026"
ARQUIVO_CHAVE = Path.home() / ".construtor-workflows" / "demo_credenciais_chave"
CREDENCIAIS = [
    ("Administrador", "adm@exemplo.test"),
    ("Coordenador", "coord@exemplo.test"),
    ("Usuário base", "base@exemplo.test"),
    ("Sem papel (tela 403)", "sem@exemplo.test"),
]


def _chave_local_de_demo():
    """Chave Fernet LOCAL da demo (nunca a do .env): lida de ~/.construtor-workflows/…, criada se
    faltar. Só entra no ambiente se CREDENCIAIS_CHAVE não vier de fora (um reinício sem ela
    quebraria as Credenciais do banco de demo)."""
    if os.environ.get("CREDENCIAIS_CHAVE"):
        return
    try:
        if not ARQUIVO_CHAVE.exists():
            from cryptography.fernet import Fernet

            ARQUIVO_CHAVE.parent.mkdir(parents=True, exist_ok=True)
            ARQUIVO_CHAVE.write_text(Fernet.generate_key().decode(), encoding="utf-8")
            try:
                ARQUIVO_CHAVE.chmod(0o600)
            except OSError:  # Windows: permissões POSIX não se aplicam
                pass
        os.environ["CREDENCIAIS_CHAVE"] = ARQUIVO_CHAVE.read_text(encoding="utf-8").strip()
    except OSError:
        print("AVISO: não consegui ler/criar a chave local de demo das Credenciais.")


def _subir_worker():
    """Worker do cadastro (processar_cadastros) junto da demo; encerra com o servidor."""
    worker = subprocess.Popen(
        [sys.executable, str(RAIZ / "manage.py"), "processar_cadastros"],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.demo"},
        cwd=str(RAIZ),
    )
    atexit.register(lambda: worker.poll() is None and worker.terminate())
    return worker


def _migrar_se_pendente(call_command):
    """No reload: aplica migration nova (banco de demo é descartável) e avisa no log."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    if MigrationExecutor(connection).migration_plan(
        MigrationExecutor(connection).loader.graph.leaf_nodes()
    ):
        print("Migration nova detectada: aplicando no banco de demo.")
        call_command("migrate", verbosity=0, interactive=False)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--resetar", action="store_true", help="apaga e recria o banco de demo")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    _chave_local_de_demo()

    import django
    from django.conf import settings

    django.setup()
    import _banco
    import psycopg
    from django.core.management import call_command

    # O autoreloader do Django reexecuta este script num processo filho (RUN_MAIN=true) a cada
    # alteração de código: banco, migrate, semeadura e credenciais só no processo pai.
    filho_do_reloader = os.environ.get("RUN_MAIN") == "true"
    if filho_do_reloader:
        _migrar_se_pendente(call_command)
    else:
        config = settings.DATABASES["default"]
        try:
            if args.resetar:
                _banco.apagar(config)
            if _banco.criar_se_faltar(config) or args.resetar:
                print("Banco de demo criado.")
        except psycopg.OperationalError:
            print("AMBIENTE: não consegui falar com o Postgres local (localhost:5432).")
            return 2

        call_command("migrate", verbosity=0, interactive=False)
        call_command(
            "semear_demo", senha=SENHA_DEMO, extras=30, com_sem_papel=True, stdout=io.StringIO()
        )

        print("\nCredenciais FICTÍCIAS de demo (só valem neste banco local):")
        for rotulo, email in CREDENCIAIS:
            print(f"  {rotulo:<22} {email}   senha: {SENHA_DEMO}")
        _subir_worker()
        print(f"\nSubindo em http://127.0.0.1:{args.porta}/  (Ctrl+C para parar)")
        print("O código recarrega sozinho ao salvar; migration nova é aplicada no reload.\n")
    call_command("runserver", f"127.0.0.1:{args.porta}", use_reloader=True, insecure_serving=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
