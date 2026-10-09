"""Ponte Python → runtime JS isolado do nó Código (SEG-17, NOV-06).

Um processo `node --permission` por execução de nó: sem `--allow-*`, env vazio, memória e tempo
limitados, entrada/saída só JSON por stdin/stdout. Nunca eval/vm no processo do Django.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

RUNNER = Path(__file__).with_name("executor.mjs")
LIMITE_CODIGO = 50_000
LIMITE_SAIDA = 5 * 1024 * 1024
LIMITE_MEMORIA_MB = 128
LIMITE_CPU_S = 5


class CodigoErro(Exception):
    """Falha do nó Código; `categoria` é `codigo` ou `codigo_limite` (mensagem já segura)."""

    def __init__(self, categoria, mensagem):
        super().__init__(mensagem)
        self.categoria = categoria
        self.mensagem = mensagem


def _node():
    caminho = os.environ.get("NODE_BIN") or shutil.which("node")
    if not caminho:
        raise CodigoErro("codigo", "Runtime do nó Código indisponível (Node.js não encontrado).")
    return caminho


def executar_codigo(
    codigo, itens, modo="uma_vez_para_todos", nos=None, contexto=None, cpu_s=LIMITE_CPU_S
):
    """Roda `codigo` e devolve `{"itens": [{"json": ...}], "logs": [...], "duracao_ms": int}`."""
    if len(codigo) > LIMITE_CODIGO:
        raise CodigoErro("codigo", "O código excede 50.000 caracteres.")
    contexto = {
        "agora": "1970-01-01T00:00:00.000Z",
        "execucao_id": 0,
        "fluxo_nome": "",
        "parametros": {},
        **(contexto or {}),
    }
    carga = json.dumps(
        {
            "codigo": codigo,
            "modo": modo,
            "itens": itens,
            "nos": nos or {},
            "contexto": contexto,
            "timeoutMs": int(cpu_s * 1000),
        }
    ).encode()
    comando = [
        _node(),
        "--permission",
        f"--max-old-space-size={LIMITE_MEMORIA_MB}",
        "--disallow-code-generation-from-strings",
        str(RUNNER),
    ]
    # --permission sem --allow-fs-read bloqueia até ler o próprio runner: libera SÓ ele, leitura.
    comando.insert(2, f"--allow-fs-read={RUNNER}")
    inicio = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - lista de argumentos, sem shell
            comando,
            input=carga,
            capture_output=True,
            timeout=cpu_s + 3,
            env={},
            cwd=str(RUNNER.parent),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CodigoErro("codigo_limite", "O código excedeu o tempo limite.") from None
    duracao = int((time.monotonic() - inicio) * 1000)
    if len(proc.stdout) > LIMITE_SAIDA:
        raise CodigoErro("codigo_limite", "A saída do código excedeu 5 MB.")
    if proc.returncode != 0 and not proc.stdout:
        # estouro de memória (OOM) ou crash do runtime: nada de stderr cru para o usuário
        raise CodigoErro(
            "codigo_limite", "O código excedeu o limite de memória ou o runtime falhou."
        )
    try:
        resposta = json.loads(proc.stdout)
    except ValueError:
        raise CodigoErro("codigo", "Resposta inválida do runtime do código.") from None
    if "erro" in resposta:
        raise CodigoErro(resposta["erro"]["categoria"], resposta["erro"]["mensagem"])
    resposta["duracao_ms"] = duracao
    return resposta
