#!/usr/bin/env python
"""Check determinístico do projeto. Sem flag de "forçar verde".

Uso:
  python scripts/check.py            # completo (fim de módulo)
  python scripts/check.py --rapido   # só o que foi tocado (git diff) + testes ligados

Cada falha é classificada:
  CÓDIGO   -> o código/teste está errado (conta como ciclo vermelho)
  AMBIENTE -> Postgres fora do ar, Playwright sem navegador etc. (não conta como ciclo)
  EXTERNO  -> rede/serviço de terceiros indisponível (não conta como ciclo)
Saída: 0 = verde; 1 = há falha de CÓDIGO; 2 = só falhas de AMBIENTE/EXTERNO (não está verde).
"""

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CODIGO, AMBIENTE, EXTERNO = "CÓDIGO", "AMBIENTE", "EXTERNO"

SINAIS_AMBIENTE = (
    "connection refused",
    "connection failed",
    "could not connect",
    "is the server running",
    "executable doesn't exist",
    "playwright install",
    "browsertype.launch",
    "servidor local não subiu",  # tempo esgotado com a máquina ocupada (telas.py)
)
SINAIS_EXTERNO = (
    "connection error",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "max retries exceeded",
    "failed to establish a new connection",
    "readtimeout",
    "connecttimeout",
    "ssl:",
)


@dataclass
class Resultado:
    nome: str
    ok: bool
    classe: str | None = None
    saida: str = ""


def _env():
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.teste"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _rodar(comando):
    proc = subprocess.run(
        comando, cwd=RAIZ, env=_env(), capture_output=True, text=True, encoding="utf-8"
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _classificar(saida, padrao=CODIGO):
    minusculo = saida.lower()
    if any(s in minusculo for s in SINAIS_AMBIENTE):
        return AMBIENTE
    if any(s in minusculo for s in SINAIS_EXTERNO):
        return EXTERNO
    return padrao


def _py(*args):
    return [sys.executable, *args]


def arquivos_tocados():
    """Arquivos .py alterados ou novos segundo o git (relativos à raiz)."""
    _, mod = _rodar(["git", "diff", "--name-only", "HEAD"])
    _, novos = _rodar(["git", "ls-files", "--others", "--exclude-standard"])
    nomes = {n.strip() for n in (mod + "\n" + novos).splitlines() if n.strip()}
    return sorted(n for n in nomes if n.endswith(".py") and (RAIZ / n).exists())


def testes_ligados(tocados):
    """Testes tocados + testes de unidade do app de cada arquivo tocado em apps/<app>/."""
    testes = {t for t in tocados if t.startswith("tests/") and Path(t).name.startswith("test_")}
    for t in tocados:
        partes = Path(t).parts
        if len(partes) > 2 and partes[0] == "apps" and (RAIZ / "tests/unit" / partes[1]).is_dir():
            testes.add(f"tests/unit/{partes[1]}")
        if partes[0] in ("config", "scripts") and (RAIZ / "tests/unit" / partes[0]).is_dir():
            testes.add(f"tests/unit/{partes[0]}")
    if any(Path(t).name == "conftest.py" or t.startswith("tests/conftest") for t in tocados):
        testes.add("tests/unit")
    return sorted(testes)


def passo(nome, comando, padrao=CODIGO):
    codigo, saida = _rodar(comando)
    if codigo == 0:
        return Resultado(nome, True, saida=saida)
    return Resultado(nome, False, _classificar(saida, padrao), saida)


def checar_ssrf_liberar():
    """SEG-08: MOTOR_SSRF_LIBERAR vazia em base, dev e teste."""
    codigo = (
        "import importlib,sys\n"
        "ruins=[m for m in ('base','dev','teste') "
        "if importlib.import_module('config.settings.'+m).MOTOR_SSRF_LIBERAR]\n"
        "print('MOTOR_SSRF_LIBERAR não está vazia em: '+', '.join(ruins)) if ruins else None\n"
        "sys.exit(1 if ruins else 0)\n"
    )
    codigo_saida, saida = _rodar(_py("-c", codigo))
    return Resultado("MOTOR_SSRF_LIBERAR vazia (SEG-08)", codigo_saida == 0, CODIGO, saida)


def limpar_bancos_orfaos():
    """Início do check: apaga bancos temporários de execuções já mortas (não conta como etapa)."""
    codigo = (
        "import sys; sys.path.insert(0, 'scripts')\n"
        "import dj_database_url, _banco\n"
        "cfg = dj_database_url.parse('postgres://localhost:5432/postgres')\n"
        "print(len(_banco.limpar_orfaos(cfg)))\n"
    )
    codigo_saida, saida = _rodar(_py("-c", codigo))
    if codigo_saida == 0 and saida.strip() not in ("", "0"):
        print(f"[limpeza] {saida.strip()} banco(s) temporário(s) órfão(s) apagado(s).")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--rapido", action="store_true", help="só arquivos tocados (git diff)")
    parser.add_argument(
        "--modulo",
        type=int,
        help="limita os testes aos marcados com modulo('mN') até N (ex.: --modulo 0 na Fase 0)",
    )
    args = parser.parse_args()
    limite = ["--modulo-ate", str(args.modulo)] if args.modulo is not None else []

    limpar_bancos_orfaos()
    resultados = []
    if args.rapido:
        tocados = arquivos_tocados()
        print(f"[rápido] {len(tocados)} arquivo(s) .py tocado(s).")
        if tocados:
            resultados.append(
                passo("ruff lint", _py("-m", "ruff", "check", "--force-exclude", *tocados))
            )
            resultados.append(
                passo(
                    "ruff format",
                    _py("-m", "ruff", "format", "--check", "--force-exclude", *tocados),
                )
            )
        testes = testes_ligados(tocados) or ["tests/unit"]
        resultados.append(passo("pytest", _py("-m", "pytest", "-q", *limite, *testes)))
    else:
        resultados.append(passo("ruff lint", _py("-m", "ruff", "check", ".")))
        resultados.append(passo("ruff format", _py("-m", "ruff", "format", "--check", ".")))
        resultados.append(
            passo(
                "makemigrations --check --dry-run",
                _py("manage.py", "makemigrations", "--check", "--dry-run"),
            )
        )
        resultados.append(checar_ssrf_liberar())
        resultados.append(
            passo(
                "pytest + cobertura",
                _py(
                    "-m",
                    "pytest",
                    "-q",
                    *limite,
                    "--cov",
                    "--cov-report=term-missing:skip-covered",
                ),
            )
        )
        resultados.append(
            passo("pip-audit", _py("-m", "pip_audit", "-r", "requirements.txt"), EXTERNO)
        )
        resultados.append(
            passo(
                "telas: sem console error / overflow 390px", _py("scripts/telas.py", "--verificar")
            )
        )

    print()
    for r in resultados:
        marca = "OK     " if r.ok else f"FALHOU ({r.classe})"
        print(f"- {r.nome}: {marca}")
    falhas = [r for r in resultados if not r.ok]
    for r in falhas:
        print(f"\n===== {r.nome} [{r.classe}] =====")
        print(r.saida[-4000:].rstrip())
    if any(r.classe == CODIGO for r in falhas):
        print("\nRESULTADO: VERMELHO (código).")
        return 1
    if falhas:
        print("\nRESULTADO: NÃO VERDE — só falhas de ambiente/externas (não contam como ciclo).")
        return 2
    print("\nRESULTADO: VERDE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
