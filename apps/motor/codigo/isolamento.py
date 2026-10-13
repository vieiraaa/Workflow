"""Segunda parede de rede do nó Código (SEG-20, D-027).

O `--permission` do Node 24 não cobre rede; a barreira de rede do `vm` não é fronteira de
segurança. Por isso o processo do runtime roda DENTRO de uma camada do sistema operacional que nega
rede, independente do vm:

- macOS: `sandbox-exec` com perfil `(deny network*)`;
- Linux: namespace de rede vazio (`unshare --net`, com `--map-root-user` para uso sem root).

FALHA FECHADA: sem camada disponível (ex.: Windows hoje) o nó Código não roda
(`codigo_indisponivel`). Não há opção para desligar a camada. Tudo com lista de argumentos
(sem shell); a camada é validada de verdade (uma sonda a executa) antes de ser usada.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

MSG_INDISPONIVEL = "O nó Código não está disponível neste servidor (sem isolamento de rede)."
PERFIL_MACOS = "(version 1)(allow default)(deny network*)"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _prefixos_candidatos():
    if sys.platform == "darwin":
        yield "sandbox-exec", [SANDBOX_EXEC, "-p", PERFIL_MACOS]
    elif sys.platform.startswith("linux"):
        unshare = shutil.which("unshare")
        if unshare:
            yield "unshare", [unshare, "--net", "--map-root-user"]
            yield "unshare", [unshare, "--net"]


def _funciona(prefixo):
    """Sonda: roda um comando trivial dentro da camada (o prefixo existir não basta)."""
    verdadeiro = shutil.which("true") or "/usr/bin/true"
    try:
        resultado = subprocess.run(  # noqa: S603 - lista de argumentos, sem shell
            [*prefixo, verdadeiro], capture_output=True, timeout=10, env={}, check=False
        )
    except OSError, subprocess.SubprocessError:
        return False
    return resultado.returncode == 0


@lru_cache(maxsize=1)
def camada():
    """`(nome, prefixo_do_comando)` da camada de rede disponível, ou None (falha fechada)."""
    for nome, prefixo in _prefixos_candidatos():
        if _funciona(prefixo):
            return nome, tuple(prefixo)
    return None


def disponivel():
    return camada() is not None


def comando(argv):
    """`argv` envolvido pela camada. `None` se não há camada: o chamador deve falhar fechado."""
    encontrada = camada()
    return None if encontrada is None else [*encontrada[1], *argv]


def node_real():
    """O node de verdade (nunca o lançador de testes): NODE_REAL ou o `node` do PATH."""
    return os.environ.get("NODE_REAL") or shutil.which("node")


def criar_lancador(diretorio=None):
    """Script POSIX que executa `node` dentro da camada (`lancador args...`) ou None.

    Serve só para testes que lançam o node por conta própria e precisam da mesma parede do
    produto (o teste de prova de rede do Revisor usa NODE_BIN). O executor do motor NÃO lê
    NODE_BIN: ele sempre envolve o node pela camada.
    """
    real, completo = node_real(), comando([node_real() or ""])
    if real is None or completo is None or os.name == "nt":
        return None
    pasta = Path(diretorio or tempfile.mkdtemp(prefix="node-isolado-"))
    destino = pasta / "node-isolado"
    destino.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(p) for p in completo) + ' "$@"\n')
    destino.chmod(0o755)
    return str(destino)
