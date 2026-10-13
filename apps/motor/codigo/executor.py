"""Ponte Python → runtime JS isolado do nó Código (SEG-17, NOV-06).

Um processo `node --permission` por execução de nó: sem `--allow-*`, env vazio, memória e tempo
limitados, entrada/saída só JSON por stdin/stdout. Nunca eval/vm no processo do Django.
"""

import json
import subprocess
import time
from pathlib import Path

from . import isolamento

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


def _comando():
    """Comando do runtime DENTRO da camada de rede do SO (SEG-20); falha fechada sem ela."""
    node = isolamento.node_real()
    if not node:
        raise CodigoErro(
            "codigo_indisponivel", "Runtime do nó Código indisponível (Node.js não encontrado)."
        )
    argv = [
        node,
        "--permission",
        f"--allow-fs-read={RUNNER}",  # só o próprio runner, leitura
        f"--max-old-space-size={LIMITE_MEMORIA_MB}",
        "--disallow-code-generation-from-strings",
        str(RUNNER),
    ]
    envolvido = isolamento.comando(argv)
    if envolvido is None:
        raise CodigoErro("codigo_indisponivel", isolamento.MSG_INDISPONIVEL)
    return envolvido


def executar_codigo(
    codigo, itens, modo="uma_vez_para_todos", nos=None, contexto=None, cpu_s=LIMITE_CPU_S
):
    """Roda `codigo` no runtime isolado. Devolve, conforme o modo:

    - `uma_vez_para_todos`: `{"itens": [{"json": ...}], "logs": [...], "duracao_ms": int}`;
    - `uma_vez_por_item`: `{"por_item": [{"itens": [...]} | {"erro": mensagem}], "logs": [...],
      "duracao_ms": int}` (uma entrada por item de entrada, na ordem; falha de um item não impede
      os outros).

    Falha do código inteiro: `CodigoErro` (`codigo`, `codigo_limite` ou `codigo_indisponivel`).
    """
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
    comando = _comando()
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
    except OSError:
        raise CodigoErro("codigo_indisponivel", isolamento.MSG_INDISPONIVEL) from None
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
