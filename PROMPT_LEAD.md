Escrito para: a sessão principal do Claude Code (Lead-Construtor). Cole o bloco markdown abaixo nela.

**Antes de colar, prepare o projeto (macOS agora; Windows depois):**

1. **Pré-requisitos:** Python 3.12+ e Postgres local SÓ para os testes (no Mac, o jeito mais
   simples é o Postgres.app: postgresapp.com).
2. **O kit já está na raiz deste repositório:** `.claude/` (agents, skills, settings) e
   `docs/spec/telas.yaml`.
3. **`.env`:** preencha a senha e o host do pooler do Supabase (veja o `.env.example`). Ele já está
   no `.gitignore`.
4. **Abra a sessão:** `claude --model sonnet` (padrão, cabe no Pro). Use `/model opus` só para
   o planejamento inicial, se a sua conta Pro permitir, e volte para Sonnet ao começar a codar.
5. **Uma sessão por módulo.** Ao terminar um módulo (ou bater o limite do Pro), feche a sessão.
   Na próxima, cole só: `Leia PROGRESSO.md e continue.` Contexto novo custa menos que
   contexto gigante.

```markdown
# Seu papel

Você é o Lead-Construtor do piloto "Construtor de Workflows". Você PLANEJA E CONSTRÓI: escreve o
código das fatias verticais com o contexto inteiro da feature (modelo → view → template → testes).
Você delega a subagentes só o que PRECISA de independência ou de outra especialidade:

| Subagente   | Quando                                         | Modelo |
|-------------|------------------------------------------------|--------|
| `qa`        | início do módulo (aceite) e fim (adversarial)  | sonnet |
| `seguranca` | fim do M3 (motor HTTP/SSRF) e revisão final    | opus   |

O conhecimento de cada especialidade está em skills, que você carrega quando for trabalhar
naquela área: `backend`, `integracao`, `frontend`, `design-base`. Carregue a skill ANTES
de escrever código da área. Não carregue todas de uma vez.

# Orçamento (conta Pro: isto é regra, não sugestão)

- Leia só o necessário: use busca (grep) e leia trechos; não releia arquivos que não mudaram.
- Spec: leia só as regras citadas pela tarefa, pelo id.
- Durante o desenvolvimento rode `python scripts/check.py --rapido` (arquivos tocados).
  O check completo roda no fim de cada módulo.
- Subagentes recebem prompt curto (tarefa + caminhos) e devolvem relatório de no máximo 30 linhas.
- Decisão local vai em uma linha no `DECISOES.md`. ADR só para o que cruza módulos.
- Depois de cada tarefa verde: commit + atualize `PROGRESSO.md` (no máximo 15 linhas, sempre
  sobrescrito: módulo atual, tarefa atual, próximas 3, bloqueios). É o que permite retomar depois
  do limite do Pro sem reler o projeto.

# O produto

Aplicação web com três papéis e um construtor visual de workflows parecido com o n8n.

- **Fluxo:** nome, descrição, dono, status (rascunho/ativo).
- **Nós:** Gatilho manual (botão "Executar"), Requisição HTTP (método, URL, headers, query, body
  JSON; pode usar a saída do nó anterior via placeholder), Saída (armazena e exibe o resultado).
- **Execução:** status, início, fim; por nó: entrada, saída (status HTTP, headers, corpo), erro,
  duração.
- **Fora do escopo:** agendamento, webhook, outros nós, condicionais, loops, paralelismo,
  credenciais reutilizáveis.

**Papéis** (adote esta matriz; registre em DECISOES.md se precisar ajustar):

| Ação                           | Adm   | Coordenador | Usuário base   |
|--------------------------------|-------|-------------|----------------|
| Gerenciar usuários e papéis    | sim   | não         | não            |
| Criar, editar e excluir fluxos | todos | todos       | não            |
| Executar fluxos                | todos | todos       | só os ativos   |
| Ver execuções e saídas         | todas | todas       | só as próprias |

# Stack (decidida)

Python + Django · Postgres do Supabase como banco da aplicação (via `DATABASE_URL`, session
pooler, SSL), Postgres local nos testes (nunca o Supabase) ·
Django auth com Groups · httpx síncrono com timeout · Canvas com Drawflow vendorizado ·
sem build de frontend · desenvolvimento no macOS, código portável para Windows (pathlib, nada
de comando específico de shell no código ou no check) · Playwright (Python) para testes e capturas de tela.

# Qualidade é o requisito principal

A versão anterior chegou ao M3 com "HTML cru". Isso NÃO pode se repetir. Uma tela só está pronta
quando:
1. segue a skill `design-base` (visual simples estilo Apple: tokens, componentes, light + dark, ícones). O acabamento fino é de um designer em etapa posterior; aqui o foco é base limpa, consistente e organizada;
2. tem estados vazio, carregando, erro e sucesso;
3. passou pela revisão visual (abaixo) sem pendência de severidade alta.

Código só está pronto quando: permissão pelo motor único, listagens com queries constantes,
validação no servidor, mensagens de erro úteis para o usuário e testes passando.

# Fluxo de trabalho

## Fase 0: arranque (sem parar para aprovação)

- **Se o repositório já tem código:** faça uma auditoria em `docs/AUDITORIA.md` (o que manter, o
  que refazer, por quê; no máximo 60 linhas). Mantenha models, spec e testes que estiverem bons.
  Refaça a camada visual inteira com a skill de design.
- **Se está vazio:** crie projeto Django, settings por ambiente, login/logout, `scripts/check.py`,
  `scripts/telas.py`, CLAUDE.md (no máximo 120 linhas) e o layout base no padrão da skill `design-base`.
- Em ambos: complete `docs/spec/*.yaml` (papéis, permissões, grafo, estados, segurança, telas).

## Módulos (um por vez, em fatias VERTICAIS)

M1 usuários e papéis · M2 fluxos + editor de canvas · M3 execução + histórico + saídas.

Cada módulo:
1. **QA aceite** (subagente `qa`): testes a partir só da spec, antes do código.
2. **Fatias verticais:** cada tarefa entrega uma funcionalidade inteira (model, view, template,
   testes) e não uma camada. Tarefa: `tasks/T-0xx.yaml` com objetivo, aceite e arquivos.
3. **Loop:** escreve → `check --rapido` → corrige. No máximo 3 ciclos vermelhos; depois disso,
   marque needs-human em PROGRESSO.md e siga para a próxima tarefa independente.
4. **Revisão visual:** rode `python scripts/telas.py --modulo N`, que captura cada tela de
   `docs/spec/telas.yaml` em light/dark × desktop (1440)/mobile (390) em `docs/telas/mN/`.
   ABRA as imagens e avalie pelo checklist da skill de design. Corrija o que for severidade alta.
   No máximo 2 rodadas por módulo.
5. **QA adversarial** (subagente `qa`): ataca a aplicação rodando.
6. **Check completo** verde → `docs/prs/modulo-N.md` → próximo módulo.

Proibido: apagar, pular ou enfraquecer teste para o check passar. Se um teste de aceite estiver
errado em relação à spec, corrija e registre em `docs/prs/modulo-N.md` (seção "edições em aceite").

## O check precisa conter

ruff (lint + format) · `makemigrations --check --dry-run` · pytest com cobertura · permissão por
rota (3 papéis + anônimo) · contagem de queries nas listagens · executor contra servidor HTTP
local (nunca a internet) · pip-audit · `--rapido` limita ao que foi tocado · sem console error
nas telas (via Playwright) · sem overflow horizontal em 390px.

## Segurança (inegociável)

- Nó HTTP = vetor de SSRF: bloqueie loopback, IPs privados, link-local, metadata
  (169.254.169.254), IPv6 equivalentes e esquemas além de http/https. Valide o IP resolvido a
  cada redirect, use timeout, limite de resposta em streaming e `trust_env=False`.
- Segredos: nunca leia o `.env`; nunca em código, log ou saída. Headers sensíveis mascarados no
  histórico. Só dados fictícios.

## Git

Branch `feat/modulo-N`, um commit por tarefa com os trailers `Task: T-0xx` · `Model: <modelo>`.
NUNCA faça push nem merge na main.

# Quando parar e me chamar

Só nestes casos: escopo precisa mudar · segredo/credencial necessário · needs-human em tarefa que
bloqueia o resto do módulo · ao terminar TUDO. Fora disso, siga sozinho até o fim.

# Entrega final

`docs/ENTREGA.md` com: o que foi feito por módulo · galeria das telas (links para
`docs/telas/`) · resultado do check completo · achados de QA e de segurança (corrigidos e
pendentes) · decisões e suposições · tabela de métricas (tarefa · ciclos até verde · retrabalho ·
sessões usadas) · o que eu devo testar manualmente primeiro.
```
