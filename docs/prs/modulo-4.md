# M4 · Home (visão geral) e Setores — branch `feat/modulo-4`

Pedido do usuário (08/10/2026): uma tela principal com indicadores, períodos e gráficos de operação, e visibilidade
por papel — Administrador vê 100% do banco, gestor só o seu setor, usuário só o que é dele.
Decisões do usuário: **Coordenador = Gestor do setor**, com cadastro de **Setores**; a regra vale no **sistema inteiro**.

## O que entra
- **Setores** (SET-01..07): cadastro só do Adm (criar, renomear, ativar/desativar; sem exclusão); usuário pertence a um
  setor; fluxo herda o setor do dono (só o Adm move); execução guarda o setor do fluxo no momento (snapshot). Migração de
  dados cria o setor "Geral" e vincula tudo o que já existia.
- **Escopo por setor no sistema inteiro** (SET-06): Adm = tudo (com ou sem setor); Coordenador = só o setor dele;
  Base = fluxos ativos do setor dele e só as próprias execuções. Fora do escopo = 404. O motor de permissões lê a matriz
  da spec (`docs/spec/permissoes.yaml`: escopos `setor` e `ativos_do_setor`), sem regra duplicada no código (D-005).
- **Home** (HOM-01..09), rota `/`: cartões de indicadores com variação vs. período anterior (fluxos ativos e em
  rascunho, execuções, taxa de sucesso, erros, duração média, usuários e setores ativos conforme o papel); seletor
  24h · 7d · 30d · 6m · 1a (fuso America/Sao_Paulo, intervalos exatos); gráfico de execuções (sucesso × erro
  empilhados, hachura no erro), erros por categoria, execuções por setor (Adm), top 5 fluxos e últimas 10 execuções
  com linha clicável; estados vazio/sem dados/carregando; 390 px e light/dark.
- Gráficos em **SVG próprio**, acessíveis (título, eixos, tooltip e tabela "Ver dados"), sem biblioteca externa (D-019).

## Qualidade técnica
- Todas as contagens e séries por **agregação no banco**; número de consultas constante; índices em
  (setor, iniciada_em) e (status, iniciada_em); Home < 300 ms com 10 mil execuções (teste).
- Contrato da Home fechado na spec antes do código (HOM-09): `data-indicador`/`data-valor`/`data-variacao`, formatos,
  `json_script` `home-serie`/`home-erros`/`home-setores`.

## Testes
- Aceite M4 (Lupa, só pela spec): 175 testes — setores, escopo por setor em TODAS as rotas, Home por papel e período.
- Adversarial M4 (Lupa, caixa-preta): **252 ataques, 0 achados** — vazamento entre setores em rotas, filtros, Home e
  JSON; mass assignment de setor; sessão aberta após troca de setor/papel; setor desativado; XSS no nome do setor
  (chromium e webkit).
- Unidade (Forja, Vitral): motor de escopo, agregações, intervalos, render das telas, e2e da Home.
- Check completo (09/10, time pausado): **VERDE** — ruff, format, makemigrations, SEG-08, pytest (2.033 testes, 0
  falhas), telas (sem console error, sem overflow a 390 px). pip-audit falhou por rede na rodada do check (EXTERNO);
  rodado em seguida: "No known vulnerabilities found".
- Antes do verde, o check acusou 8 testes adversariais ANTIGOS (m1: 7, m3: 1) que criavam usuários sem setor — não era
  defeito de código; a QA os atualizou à spec do M4 sem enfraquecer o ataque (`324f919`).

## Revisão visual
Rodada 1 (40 capturas em `docs/telas/m4/`, TEL-13..17, light/dark × 1440/390): 0 altas. Média corrigida: a
semeadura de demo fazia o Usuário base executar fluxos de outros setores (violava SET-06) → corrigida (`ee77faf`).

## Edições em aceite (justificadas)
- `tests/acceptance/m4/test_home.py` (4 testes): isolados da fixture compartilhada que criava execuções extras.
- `tests/acceptance/m1/test_login.py` e `test_permissoes.py` (6): PRM-07 revisado — `/` é a Home, não redireciona mais.
- `tests/acceptance/m1/test_usuarios.py` (7): SET-03 — Coordenador/Base passam a exigir setor.
Todas feitas pela própria QA, após mudança de spec decidida pelo Lead (`14604fe`).

## Para revisar no PR
- `apps/contas/permissoes.py` (escopos `setor`/`ativos_do_setor`), `apps/execucoes/painel.py` (agregações),
  migrations de `contas`, `fluxos` e `execucoes` (setor + dados "Geral"), `templates/inicio/`, `static/js/graficos.js`.

## Decisão pendente do usuário
- **SET-07 (a):** gestor de um setor DESATIVADO criando fluxo — hoje o fluxo é criado no setor desativado.
  Alternativa: recusar com "Seu setor está desativado. Fale com o administrador."

## Implantação (após o merge do PR)
1. Aplicar as migrations no Supabase (`manage.py migrate --settings=config.settings.dev`) — cria setores e vincula
   tudo a "Geral". Só com OK do usuário.
2. Atualizar a cópia estável do servidor (`../construtor-workflows-estavel`) para a nova `main` (D-018) e reiniciar o
   terminal "Servidor · Supabase (estável)".
3. No Supabase, vincular os usuários reais aos setores corretos (hoje todos ficam em "Geral").

## Custo estimado (API) do M4
Construtores e QA ≈ US$ 9,2 (T-040 1,62 · T-041 1,18 · T-042 0,98 · T-043 1,77 · T-044 2,92 · T-045 0,72), mais a
coordenação do Lead. Time acumulado no projeto ≈ US$ 112 (`python3 docs/metricas/metricas.py`).
