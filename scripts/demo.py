#!/usr/bin/env python
"""Servidor de demonstração local, só com dados fictícios.

  python scripts/demo.py              # cria o banco local se faltar, migra, semeia e sobe em :8000
  python scripts/demo.py --porta 8010
  python scripts/demo.py --resetar    # apaga e recria o banco de demo

Usa config.settings.demo: Postgres local (construtor_demo), nunca o .env nem o Supabase.
"""

import argparse
import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.demo"  # forçado: nunca dev/.env

SENHA_DEMO = "Demo-Senha-Local-2026"
CREDENCIAIS = [
    ("Administrador", "adm@exemplo.test"),
    ("Coordenador", "coord@exemplo.test"),
    ("Usuário base", "base@exemplo.test"),
    ("Sem papel (tela 403)", "sem@exemplo.test"),
]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--resetar", action="store_true", help="apaga e recria o banco de demo")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    import django
    from django.conf import settings

    django.setup()
    import _banco
    import psycopg
    from django.core.management import call_command

    config = settings.DATABASES["default"]
    try:
        if args.resetar:
            _banco.apagar(config)
        if _banco.criar_se_faltar(config) or args.resetar:
            print("Banco de demo criado.")
    except psycopg.OperationalError:
        print("AMBIENTE: não consegui falar com o Postgres local (localhost:5432). Ele está no ar?")
        return 2

    call_command("migrate", verbosity=0, interactive=False)
    call_command(
        "semear_demo", senha=SENHA_DEMO, extras=30, com_sem_papel=True, stdout=io.StringIO()
    )

    print("\nCredenciais FICTÍCIAS de demo (só valem neste banco local):")
    for rotulo, email in CREDENCIAIS:
        print(f"  {rotulo:<22} {email}   senha: {SENHA_DEMO}")
    print(f"\nSubindo em http://127.0.0.1:{args.porta}/  (Ctrl+C para parar)\n")
    call_command("runserver", f"127.0.0.1:{args.porta}", use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
