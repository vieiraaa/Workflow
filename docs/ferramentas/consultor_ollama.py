# ruff: noqa: E501 — textos de prompt em prosa; quebrar as linhas prejudica a leitura.
"""Consultor local (Ollama): lê o histórico do projeto e propõe melhorias numa nota do Maestri.

Duas etapas, para caber num modelo local com contexto curto:
  1. leitura — cada fonte (notas do canvas e documentos do repositório) vai em partes; o modelo anota observações;
  2. síntese — junta as anotações e escreve a nota "Melhorias · Ollama" (uma melhoria por item, para validação).

Uso (no terminal "Ollama · Consultor"):
  python3 docs/ferramentas/consultor_ollama.py [--modelo gpt-oss:20b] [--ctx 16384] [--nota "Melhorias · Ollama"]

Regras: só modelos LOCAIS (recusa nomes ":cloud"); nada sai da máquina; não lê .env; só biblioteca padrão.
As notas do canvas são lidas com `maestri note read` (o terminal precisa estar ligado a elas).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
OLLAMA = "http://localhost:11434"
NOTAS = [
    "Relatório do Processo",
    "Organograma dos Agentes",
    "Prompt Ideal · Workflow Maestri",
    "Log de Atividades",
    "Log de Atividades · M2",
    "Log de Atividades · M3",
    "Log de Atividades · M4",
    "Log de Atividades · M5",
    "Painel",
]
ARQUIVOS = [
    "PROGRESSO.md",
    "DECISOES.md",
    "docs/ROADMAP-n8n.md",
    "docs/prs/modulo-0.md",
    "docs/prs/modulo-1.md",
    "docs/prs/modulo-2.md",
    "docs/prs/modulo-4.md",
]
TAM_PARTE = 9000

SISTEMA = (
    "Você é um consultor sênior de engenharia de software e de processos com times de agentes de IA. "
    "Analisa o histórico de um piloto: um time de agentes (Lead em Claude Opus; construtores Back e Front e um QA em "
    "Claude Sonnet; revisor de segurança em Opus) orquestrado no Maestri construiu, em Django, um construtor de "
    "workflows estilo n8n (módulos M0–M5: usuários e papéis, fluxos e editor de canvas, execução com proteção SSRF, "
    "Home com setores, motor v2 com itens, expressões, credenciais e nó Código isolado). Responda SEMPRE em português "
    "do Brasil, com objetividade, citando a fonte (nome da nota ou arquivo) de cada observação. Não invente números: "
    "use só o que estiver no texto."
)

PEDIDO_LEITURA = (
    "Fonte: {fonte} (parte {i} de {n}).\n\n---\n{texto}\n---\n\n"
    "Liste, em tópicos curtos, só o que for útil para MELHORAR o processo ou o produto:\n"
    "1) problemas, retrabalhos, riscos ou custos que aparecem aqui (com a evidência);\n"
    "2) o que você faria diferente para replicar este projeto (processo, papéis, ordem, ferramentas);\n"
    "3) melhorias concretas: operacionais, técnicas, de segurança, visuais/UX, de custo/cota, de novas funcionalidades.\n"
    "Máximo de 12 tópicos. Se a parte não tiver nada relevante, responda apenas: NADA."
)

PEDIDO_SINTESE = (
    "Abaixo estão as anotações que você fez lendo todas as fontes do projeto.\n\n---\n{anotacoes}\n---\n\n"
    "Escreva a nota final, em Markdown simples, EXATAMENTE nesta estrutura:\n"
    "## Como eu replicaria este projeto\n(até 10 linhas: ordem, papéis, ferramentas, o que manter e o que mudar)\n"
    "## As 5 melhorias de maior impacto\n(lista curta com os ids)\n"
    "## Melhorias propostas\nPara cada uma, um bloco:\n"
    "### OLL-NN · <título curto>\n"
    "- Categoria: processo | operacional | técnica | segurança | visual/UX | custo e cota | nova funcionalidade\n"
    "- Evidência: <o que no histórico mostra o problema, com a fonte>\n"
    "- Proposta: <o que fazer, concreto>\n"
    "- Justificativa: <por que melhora>\n"
    "- Impacto: alto|médio|baixo · Esforço: P|M|G · Prioridade sugerida: 1..5\n"
    "- Validação do usuário: [ ] aprovar  [ ] recusar  [ ] ajustar\n"
    "Entre 12 e 25 melhorias, sem repetir. Agrupe por categoria. Não invente dados que não estejam nas anotações."
)


def maestri():
    return shutil.which("maestri") or os.environ.get("MAESTRI_CLI") or "maestri"


def ler_nota(nome):
    r = subprocess.run([maestri(), "note", "read", nome], capture_output=True, text=True)
    if r.returncode != 0 or "not found" in r.stdout.lower() or "no connection" in r.stdout.lower():
        return None
    return r.stdout


def partes(texto, tamanho=TAM_PARTE):
    blocos, atual = [], ""
    for linha in texto.splitlines(keepends=True):
        if len(atual) + len(linha) > tamanho and atual:
            blocos.append(atual)
            atual = ""
        atual += linha
    if atual.strip():
        blocos.append(atual)
    return blocos


def perguntar(modelo, ctx, conteudo):
    corpo = json.dumps(
        {
            "model": modelo,
            "stream": False,
            "options": {"num_ctx": ctx, "temperature": 0.3},
            "messages": [
                {"role": "system", "content": SISTEMA},
                {"role": "user", "content": conteudo},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA + "/api/chat", data=corpo, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=1800) as resp:  # noqa: S310 - Ollama local fixo
        dados = json.load(resp)
    return (dados.get("message") or {}).get("content", "").strip()


def gravar_nota(nome, texto):
    m = maestri()
    r = subprocess.run([m, "note", "write", nome, texto], capture_output=True, text=True)
    if r.returncode != 0 or "not found" in (r.stdout + r.stderr).lower():
        r = subprocess.run(
            [m, "note", "create", "--name", nome, texto], capture_output=True, text=True
        )
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="gpt-oss:20b")
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--nota", default="Melhorias · Ollama")
    args = ap.parse_args()
    if args.modelo.endswith(":cloud") or "cloud" in args.modelo:
        sys.exit("Recusado: use um modelo LOCAL (os dados do projeto não saem da máquina).")

    fontes = []
    for nome in NOTAS:
        texto = ler_nota(nome)
        print(("✓ nota " if texto else "· sem acesso à nota ") + nome)
        if texto:
            fontes.append((f"nota «{nome}»", texto))
    for rel in ARQUIVOS:
        p = RAIZ / rel
        if p.exists():
            fontes.append((rel, p.read_text(encoding="utf-8")))
            print("✓ arquivo " + rel)

    inicio = time.time()
    anotacoes = []
    total = sum(len(partes(t)) for _, t in fontes)
    feito = 0
    for fonte, texto in fontes:
        blocos = partes(texto)
        for i, bloco in enumerate(blocos, 1):
            feito += 1
            print(f"[{feito}/{total}] lendo {fonte} ({i}/{len(blocos)})…", flush=True)
            resposta = perguntar(
                args.modelo,
                args.ctx,
                PEDIDO_LEITURA.format(fonte=fonte, i=i, n=len(blocos), texto=bloco),
            )
            if resposta and resposta.strip().upper() != "NADA":
                anotacoes.append(f"### {fonte} ({i}/{len(blocos)})\n{resposta}")

    juntas = "\n\n".join(anotacoes)
    if len(juntas) > 40000:
        print("Condensando as anotações…", flush=True)
        juntas = "\n\n".join(
            perguntar(
                args.modelo, args.ctx, "Condense mantendo cada melhoria distinta e a fonte:\n\n" + b
            )
            for b in partes(juntas, 12000)
        )
    print("Escrevendo a síntese…", flush=True)
    nota = perguntar(args.modelo, args.ctx, PEDIDO_SINTESE.format(anotacoes=juntas))

    minutos = (time.time() - inicio) / 60
    cabecalho = (
        f"# Melhorias · Ollama\n"
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M} pelo modelo LOCAL {args.modelo} (Ollama), em {minutos:.0f} min, "
        f"a partir de {len(fontes)} fontes (notas do canvas e documentos do repositório).\n"
        f"Como usar: marque cada item e peça ao Orquestrador os aprovados. "
        f"Sugestões de um modelo local: confira a evidência antes de aprovar.\n\n"
    )
    saida = RAIZ / "docs" / "ferramentas" / "ultima_consulta_ollama.md"
    saida.write_text(cabecalho + nota, encoding="utf-8")
    ok = gravar_nota(args.nota, cabecalho + nota)
    print(
        f"✓ nota «{args.nota}» gravada"
        if ok
        else "✗ não consegui gravar a nota (texto salvo em " + str(saida) + ")"
    )
    print(f"Concluído em {minutos:.1f} min.")


if __name__ == "__main__":
    main()
