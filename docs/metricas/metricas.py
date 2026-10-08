"""Métricas por agente e tarefa (tempo, tokens, custo estimado de API).

Fonte: transcrições do Claude Code (~/.claude/projects/...jsonl) + git log do projeto.
Atribuição: cada resposta faturada de um agente vai para a tarefa do PRÓXIMO commit dele
(trailer `Task:`); depois do último commit, para a tarefa em aberto (--aberta Agente=T-0xx).
Respostas a prompts de confirmação do Lead ("Sou o Lead") ficam como "Montagem".
O Orquestrador é dividido por módulo, pelos commits de fechamento.

Uso: python metricas.py [--json] [--aberta Forja=T-011 ...]
"""

import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/arcolltechai/Documents/Projetos/construtor-workflows")
BASE = Path.home() / ".claude/projects"
PROJ = "-Users-arcolltechai-Documents-Projetos-construtor-workflows"
ROLES = f"{PROJ}--maestri-roles"
SESSOES = {
    "Forja": [
        f"{ROLES}-528e3e44-11e0-40b3-ab74-1049e7c1e589/3cc9ca65-b137-4702-844f-a0df0fb84b33.jsonl",
        f"{PROJ}/48658e53-7a30-4c49-af88-748bf1cd78e0.jsonl",
    ],
    "Vitral": [
        f"{ROLES}-8d5a63fc-bf13-4c03-bba4-4d452de804d2/99d85be3-433c-4e4a-bb05-f86cecb1fb9a.jsonl",
        f"{PROJ}/dcad4539-fbb1-4358-8d07-db325192d133.jsonl",
    ],
    "Lupa": [
        f"{ROLES}-da93f4a5-aefd-4988-b6d1-5c429379be87/b04417b9-6c14-47af-a5af-b711d7c2eea7.jsonl",
        f"{PROJ}/85e7e4bc-0239-46dd-9a1e-d56ef49e09e6.jsonl",
    ],
    "Orquestrador": [f"{PROJ}/7d97252a-3abd-4de0-a7d7-f1ee4f3584d7.jsonl"],
    "Atalaia": [f"{PROJ}/11e0bba2-6e50-49fa-aeaa-b5c8f8ae05b0.jsonl"],
}
AGENTE_TRAILER = {
    "git": "Git & Gitea",
    "back": "Forja",
    "front": "Vitral",
    "qa": "Lupa",
    "lead": "Orquestrador",
    "seguranca": "Atalaia",
}
# Marcos de módulo para o Orquestrador: (rótulo, mensagem do commit que FECHA o módulo)
MODULOS = [
    ("Fase 0", "Fase 0 fechada"),
    ("M1", "M1 fechado"),
    ("M2", "M2 fechado"),
    ("M3", "M3 fechado"),
]
# US$ por milhão de tokens: entrada, saída, escrita cache 5m, escrita cache 1h, leitura cache
PRECOS = {"sonnet": (2.00, 10.00, 2.50, 4.00, 0.20), "opus": (4.00, 20.00, 5.00, 8.00, 0.20)}


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()


def commits():
    out = subprocess.run(
        ["git", "log", "--all", "--format=%H%x1f%cI%x1f%s%x1f%b%x1e"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lista = []
    for reg in out.split("\x1e"):
        if not reg.strip():
            continue
        h, data, assunto, corpo = reg.strip().split("\x1f")
        agente = re.search(r"^Agent:\s*(\w+)", corpo, re.M)
        tarefas = re.findall(r"T-\d{3}", " ".join(re.findall(r"^Task:.*$", corpo, re.M)))
        lista.append(
            {
                "hash": h[:7],
                "data": datetime.fromisoformat(data).astimezone(),
                "assunto": assunto,
                "agente": AGENTE_TRAILER.get(agente.group(1)) if agente else None,
                "tarefa": "/".join(dict.fromkeys(tarefas)) or None,
            }
        )
    return sorted(lista, key=lambda c: c["data"])


def prompt_de(o):
    if o.get("type") == "user" and not o.get("isMeta"):
        c = o.get("message", {}).get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in c
        ):
            return " ".join(b.get("text", "") for b in c if isinstance(b, dict))
    if (
        o.get("type") == "attachment"
        and (o.get("attachment") or {}).get("type") == "queued_command"
    ):
        p = o["attachment"].get("prompt")
        return p if isinstance(p, str) else None
    return None


def respostas(arquivo):
    """Gera (timestamp, modelo, usage, em_montagem) por mensagem faturada, sem duplicar."""
    vistos, montagem = {}, False
    for linha in (BASE / arquivo).open():
        try:
            o = json.loads(linha)
        except json.JSONDecodeError:
            continue
        p = prompt_de(o)
        if p is not None and not p.startswith("<"):
            montagem = p.lstrip().startswith("Sou o Lead")
        if o.get("type") == "assistant" and o.get("message", {}).get("usage"):
            m = o["message"]
            vistos[m.get("id")] = (ts(o["timestamp"]), m.get("model"), m["usage"], montagem)
    return vistos.values()


def custo(modelo, u):
    pi, po, p5, p1, pr = PRECOS["opus" if "opus" in (modelo or "") else "sonnet"]
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0) if cc else u.get("cache_creation_input_tokens", 0)
    w1 = cc.get("ephemeral_1h_input_tokens", 0)
    e, s, r = (
        u.get("input_tokens", 0),
        u.get("output_tokens", 0),
        u.get("cache_read_input_tokens", 0),
    )
    return e + w5 + w1 + r, r, s, (e * pi + s * po + w5 * p5 + w1 * p1 + r * pr) / 1e6


def rotulo(agente, t, montagem, cms, abertas):
    if montagem:
        return "Montagem"
    if agente == "Orquestrador":
        for nome, marco in MODULOS:
            fim = next((c["data"] for c in cms if c["assunto"].startswith(marco)), None)
            if fim is None or t <= fim:
                return f"{nome} · coordenação"
        return "coordenação"
    prox = next((c for c in cms if c["agente"] == agente and c["tarefa"] and c["data"] >= t), None)
    return prox["tarefa"] if prox else abertas.get(agente, "após último commit")


def descobrir_sessoes():
    """Acrescenta sessões novas (após /clear ou reinício) pelo trailer `Agent:` dos commits feitos.

    Sessões sem nenhum commit não são atribuídas (ficam fora das métricas).
    """
    conhecidas = {Path(a).name for arqs in SESSOES.values() for a in arqs}
    mapa = {
        "back": "Forja",
        "front": "Vitral",
        "qa": "Lupa",
        "git": "Git & Gitea",
        "seguranca": "Atalaia",
        "lead": "Orquestrador",
    }
    sessoes = {k: list(v) for k, v in SESSOES.items()}
    for arq in sorted((BASE / PROJ).glob("*.jsonl")):
        if arq.name in conhecidas:
            continue
        texto = arq.read_text(errors="ignore")
        votos = {nome: texto.count(f"Agent: {trailer}") for trailer, nome in mapa.items()}
        nome, n = max(votos.items(), key=lambda kv: kv[1])
        if n == 0:
            continue
        sessoes.setdefault(nome, []).append(f"{PROJ}/{arq.name}")
    return sessoes


def coletar(abertas):
    cms = commits()
    linhas = defaultdict(
        lambda: {
            "inicio": None,
            "fim": None,
            "in": 0,
            "cache_r": 0,
            "out": 0,
            "usd": 0.0,
            "msgs": 0,
            "tempos": [],
        }
    )
    for agente, arqs in descobrir_sessoes().items():
        for arq in arqs:
            if not (BASE / arq).exists():
                continue
            for t, modelo, u, mont in respostas(arq):
                r = linhas[(agente, rotulo(agente, t, mont, cms, abertas))]
                ent, cr, sai, usd = custo(modelo, u)
                r["inicio"] = min(r["inicio"] or t, t)
                r["fim"] = max(r["fim"] or t, t)
                r["in"] += ent
                r["cache_r"] += cr
                r["out"] += sai
                r["usd"] += usd
                r["msgs"] += 1
                r["tempos"].append(t)
    return linhas


def fmt(segundos):
    m = int(round(segundos / 60))
    return f"{m // 1440}d {m % 1440 // 60}h {m % 60:02d}min"


def dur(a, b):
    return fmt((b - a).total_seconds())


def ativo(tempos, pausa=300):
    """Soma os intervalos entre respostas consecutivas, ignorando pausas > 5 min (agente ocioso)."""
    ts_ = sorted(tempos)
    return fmt(
        sum(
            d
            for d in ((b - a).total_seconds() for a, b in zip(ts_, ts_[1:], strict=False))
            if d <= pausa
        )
    )


def k(n):
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k"


def main():
    abertas = (
        dict(a.split("=", 1) for a in sys.argv[sys.argv.index("--aberta") + 1 :])
        if "--aberta" in sys.argv
        else {}
    )
    linhas = coletar(abertas)
    if "--json" in sys.argv:
        print(
            json.dumps(
                {
                    f"{a}|{r}": {
                        **v,
                        "inicio": v["inicio"].isoformat(),
                        "fim": v["fim"].isoformat(),
                        "duracao": dur(v["inicio"], v["fim"]),
                        "ativo": ativo(v["tempos"]),
                        "tempos": None,
                    }
                    for (a, r), v in linhas.items()
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return
    tot = defaultdict(lambda: [0, 0, 0.0])
    for (a, r), v in sorted(linhas.items(), key=lambda x: (x[0][0], x[1]["inicio"])):
        janela = f"{v['inicio']:%d/%m %H:%M} → {v['fim']:%d/%m %H:%M}"
        tempo = f"{dur(v['inicio'], v['fim'])} | ativo {ativo(v['tempos'])}"
        uso = f"in {k(v['in'])} (cache {k(v['cache_r'])}) | out {k(v['out'])}"
        print(f"{a:12} | {r:22} | {janela} | {tempo} | {uso} | US$ {v['usd']:.2f}")
        tot[a][0] += v["in"]
        tot[a][1] += v["out"]
        tot[a][2] += v["usd"]
    print()
    for a, (i, o, c) in tot.items():
        print(f"TOTAL {a:12} | in {k(i)} | out {k(o)} | US$ {c:.2f}")
    ti, to, tc = (sum(x[n] for x in tot.values()) for n in range(3))
    print(f"TOTAL {'TIME':12} | in {k(ti)} | out {k(to)} | US$ {tc:.2f}")


if __name__ == "__main__":
    main()
