---
name: integracao
description: Regras do motor de execução, cliente HTTP, proteção SSRF, mascaramento de segredos, settings, banco e scripts/check.py do Construtor de Workflows. Carregue antes de mexer em apps/motor/, config/settings/, requirements, conftest ou scripts/.
---

# Motor, segurança e infraestrutura

## Motor (`apps/motor/`)
- Executor sequencial: percorre o grafo a partir do Gatilho, valida o grafo antes de começar
  (um gatilho, sem ciclos, sem nó solto) e grava `ExecucaoNo` por nó (entrada, saída, erro,
  duração em ms). Uma falha encerra a execução com status `erro` e mantém o que já rodou.
- Placeholders: sintaxe `{{ anterior.corpo.campo }}` resolvida por um parser próprio e restrito.
  Proibido `eval`, `exec` e engine de template sobre entrada do usuário (ruff banned-api).
- Mascaramento: `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `Proxy-Authorization` e
  qualquer header com `token`/`secret`/`senha` aparecem como `••••` no histórico.

## Cliente HTTP e SSRF
- `httpx.Client(trust_env=False, follow_redirects=False, timeout=...)`.
- Fluxo: resolver placeholders → validar esquema (http/https) → resolver DNS → validar TODOS os
  IPs (bloquear loopback, privados, link-local, CGNAT 100.64/10, multicast, reservados,
  169.254.169.254 e equivalentes IPv6, inclusive IPv4 mapeado em IPv6) → conectar ao IP validado
  com o Host original → redirect manual (máx. 5), revalidando cada destino.
- Resposta lida em streaming com limite de tamanho (spec `seguranca.yaml`); acima disso, corta e
  marca `truncado: true`.
- Erros para o usuário: categoria clara (`bloqueado_ssrf`, `timeout`, `dns`, `conexao`,
  `resposta_grande`, `http_4xx`, `http_5xx`). Nunca imprima a mensagem crua de exceção do driver.

## Infra
- Settings por ambiente (`config/settings/base.py`, `dev.py`, `teste.py`). Teste usa Postgres local
  e falha se `DATABASE_URL` apontar para Supabase (trava em `config/travas.py`).
- Nunca leia o `.env` com ferramenta; o código lê as variáveis em tempo de execução.
- Dependência nova: confirme wheel para macOS E Windows na versão de Python do projeto antes de
  adicionar (o projeto vai para Windows depois).
- Código e `scripts/check.py` portáveis: `pathlib`, `sys.executable`, `subprocess` com lista de
  argumentos; nada de comando de shell específico de macOS ou de Windows.

## Supabase (banco da aplicação)
- Conexão só por `DATABASE_URL` (lida do ambiente com `dj-database-url` ou equivalente), nunca
  montada com valores no código.
- Use o **session pooler** (porta 5432 do `pooler.supabase.com`): a conexão direta
  (`db.<ref>.supabase.co`) costuma ser só IPv6. Não use o transaction pooler (porta 6543) com o
  Django: ele quebra prepared statements e cursores de servidor.
- `sslmode=require` e `CONN_MAX_AGE` moderado (ex.: 60) com `CONN_HEALTH_CHECKS = True`.
- Migrations no Supabase só quando o Lead pedir, nunca a partir dos testes.

## `scripts/check.py`
- Determinístico, explica cada vermelho, sem flag de "forçar verde".
- `--rapido`: ruff e pytest só nos arquivos tocados (git diff) + testes ligados a eles.
- Sem flag: check completo (ver PROMPT do lead).
- Classifica falhas como CÓDIGO, AMBIENTE (ex.: Postgres fora do ar) ou EXTERNO; AMBIENTE e
  EXTERNO não contam como ciclo vermelho.
