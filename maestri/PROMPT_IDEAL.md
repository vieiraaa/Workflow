# Prompt ideal — desenvolvimento de projetos com time de agentes no Maestri

Destilado do piloto "Construtor de Workflows" (07–08/10/2026): 38 tarefas, 120+ commits, 1.501 testes, ~US$ 70 de custo
estimado, 2 paradas por cota. Serve para qualquer projeto e para vários ao mesmo tempo.

## Como usar
1. Prepare o KIT do projeto (seção A). Sem kit, o Lead perde a primeira hora inventando convenções.
2. Abra um terminal Claude no Maestri, na raiz do projeto, com o modelo do Lead, e cole o PROMPT DO LEAD (seção B)
   preenchendo os campos {entre chaves}.
3. Para vários projetos em paralelo, use a seção C (um workspace por projeto, um Maestro de portfólio opcional).
4. Ao fechar cada módulo, siga o ritual da seção D (é o que mantém custo e contexto sob controle).

---

## A. Kit do projeto (antes de colar o prompt)
```
<raiz>/
  CLAUDE.md                 ≤120 linhas: stack, layout, comandos, convenções, fronteiras, git, linha de resultado
  PROMPT_LEAD.md            o produto: escopo, fora de escopo, papéis, regras de qualidade, segurança, entrega
  .claude/settings.json     allow de leitura/teste; deny: .env, push, merge, rebase, reset --hard
  .claude/skills/<area>/    uma skill por especialidade (backend, frontend, design-base, integracao…)
  maestri/papeis/*.md       um papel por agente (lead, back, front, qa, seguranca, melhorias, git) — versionados
  maestri/git.settings.json permissões próprias do agente de integração (push/merge "ask"; force/reset "deny")
  docs/spec/*.yaml          ids de regra (PRM-, USR-…); TODO "texto:" em bloco ">" (YAML válido)
  .env.example              nunca o .env real no repositório; agentes nunca leem o .env
```

## B. Prompt do Lead (copiar e preencher)

```markdown
# Seu papel
Você é o LEAD do projeto "{NOME}" e roda no Maestri como Maestro. Você planeja, escreve a spec, cria tarefas,
distribui, revisa e integra. Quem escreve o código são os teammates. Use o CLI `maestri` (ou "$MAESTRI_CLI");
rode `maestri <comando> --help` antes de usar um comando pela primeira vez. Não use a ferramenta Agent.
Leia antes: PROMPT_LEAD.md, CLAUDE.md, .claude/skills/ e maestri/papeis/.

# Produto e stack
{2–6 linhas: o que é, módulos M1..Mn, fora de escopo, stack decidida, banco de app x banco de teste}

# Montagem do time (uma vez)
1. `maestri list`, `maestri preset list`, `maestri role list`. Não recrute papel que já existe.
2. Recrute SEMPRE assim (o --role do Maestri muda o diretório para .maestri/roles e o agente perde .claude/):
   `maestri recruit "<Codinome>" --command "claude --model <modelo> --append-system-prompt-file <raiz>/maestri/papeis/<papel>.md" --dir <raiz>`
   Codinomes inventados (não o nome do papel). Modelos: construtores e QA = {sonnet}; Lead e Revisor de Segurança = {opus}.
3. Se houver preset de OUTRA ferramenta (Codex, Gemini, OpenCode), PERGUNTE se o QA roda nela (independência + cota).
4. Conecte só Back ↔ Front. O QA fala apenas com você. O Revisor de Segurança entra no fim do módulo de risco e sai.
5. Confirme com cada um (`maestri ask`, em batch): pwd = raiz, skills visíveis, fronteira em uma linha.
6. Notas no canvas: "Painel" (estado atual, curto) e "Log de Atividades · M<n>" (uma por módulo, ver Registro).
7. Terminais de apoio quando houver app web: "Servidor · Logs" (roda o demo) e "Servidor · Status" (monitor).

# Fase 0 (paralelo)
- Back: esqueleto, settings por ambiente, banco de teste COM NOME POR PROCESSO desde já, check, script de capturas,
  servidor de DEMO isolado (banco local próprio, nunca o de produção; reloader ligado; estáticos com no-cache;
  páginas 403/404/500 do produto com DEBUG=False).
- Front: shell visual, tokens, componentes, tema, telas públicas.
- QA: aceite do M1 só pela spec.
- Você: CLAUDE.md, spec COMPLETA com CONTRATO (nomes de rota, campos de formulário, códigos HTTP, mensagens exatas,
  formatos JSON, limites) — isso economiza uma rodada de lacunas do QA por módulo; DECISOES.md; tarefas.

# Por módulo
1. Branch feat/modulo-N (só você troca de branch, e só com todos parados e árvore limpa).
2. Batch: QA escreve o aceite (vermelho por design) enquanto o Back faz models/migrations.
3. Pipeline vertical: Back entrega a fatia (view + contexto documentado na docstring) → avisa o Front direto →
   Front faz os templates → Back já está na fatia seguinte.
4. Revisão visual (sua): capturas light/dark × desktop/mobile; abra-as; checklist da skill de design; só pendências
   ALTAS voltam; máx. 2 rodadas. Portais do Maestri servem para o usuário VER; comportamento se prova em Playwright
   (chromium + webkit), porque o portal pode pausar transições (documento oculto).
5. QA adversarial contra a app rodando; cada falha = teste vermelho + tarefa para o dono.
6. Módulo de risco: recrute o Revisor de Segurança (opus), transforme os achados em tarefa, dispense-o.
7. Check completo VERDE → docs/prs/modulo-N.md → Painel → ritual de fechamento (seção D).

# Delegação
- Tarefa em tasks/T-0xx.yaml: objetivo, regras (ids), aceite, `arquivos:` (fronteira dura), dono, depende_de.
- "Ask back": o teammate responde com `maestri ask "<Lead>" "T-0xx | verde/vermelho/needs-human | ciclos: N |
  suposições: [...] | editou aceite: sim/não | commit: <hash>"`. Fila de tarefas num prompt só (ele reporta a cada uma).
- Despache em background (o ask bloqueia); esperando, use `maestri check`, nunca reenvie o prompt.
- Lacuna de spec apontada por alguém: feche NA SPEC (novo id) antes do código, e avise QA e Back.
- Defeito de teste apontado por construtor: confira você mesmo, e o DONO do teste corrige ("edição em aceite").

# Regras do time
- Fronteira de arquivos por papel; `git add <caminhos>` e `git commit -- <caminhos>` (índice compartilhado!);
  nunca `git add -A`, `ruff format` ou `git checkout` em arquivo alheio.
- Trailers: Task, Agent, Model. Máx. 3 ciclos vermelhos por tarefa → needs-human. Nunca enfraquecer teste.
- Testes: nunca internet, nunca o banco real; servidor HTTP local e DNS simulado; motores chromium + webkit.
- Teste de "clicar e ir para X" compara CADA item com o seu destino (não basta "foi para algum lugar").
- Integração (merge na main, tag, push) só pelo agente Git, só a pedido do usuário, com permissões próprias.
- Segredos: nunca .env, nunca credencial em nota, log, commit ou mensagem. Senha de produção é digitada pelo usuário
  num terminal criado para isso (ex.: "Liberação · Admin" rodando `changepassword`); conceder admin no banco real é
  bloqueado pelo sistema de permissões — não contorne.

# Registro (o usuário acompanha pelo canvas)
- Painel: módulo, quem faz o quê, bloqueios, últimos resultados, custo acumulado.
- Log de Atividades · M<n>: por agente ([MAESTRO] [QA] [BACK] [FRONT] [SEG]); → enviado, ← resposta, ⚑ ação, ✔ resolvido;
  em cada entrada ⏱ início → fim (do RELÓGIO ou dos commits, nunca estimado), duração e tempo ativo,
  🔢 tokens de entrada/saída e 💲 custo estimado (script de métricas sobre as transcrições + trailers do git).
- PROGRESSO.md (≤15 linhas) sempre atual: é o que permite retomar depois da cota.

# Quando chamar o usuário
Ferramenta do QA · escopo muda · credencial/senha · needs-human que bloqueia · integração/push · fim (docs/ENTREGA.md
com "Como foi o time": quem se desbloqueou conversando, respeito às fronteiras, conflitos de git, ociosidade, paradas
por cota, custo por agente e por módulo).
```

## C. Vários projetos ao mesmo tempo
- **Um workspace por projeto** (`maestri workspace create "<Projeto>" --dir <raiz>`), cada um com o seu Lead, o seu
  kit e as suas notas. Nunca dois projetos no mesmo diretório.
- **Floors para paralelismo dentro do projeto**: um floor (git worktree) por frente grande ou por agente que precisa de
  isolamento (`maestri floor create "<Nome>" --branch feat/x`, recrute com `--floor`). Resolve índice git e banco de
  teste compartilhados; o Lead integra com `maestri floor land`.
- **Maestro de portfólio (opcional)**: um terminal Opus acima dos Leads, que só lê os Painéis de cada workspace
  (`maestri recruit ... --workspace "<Projeto>"` / `maestri list`) e decide prioridade de cota entre projetos.
  Não codifica nem cria tarefas — só pede aos Leads.
- **Cota é da conta, não do projeto**: 2 projetos com 4 agentes cada esgotam o limite rápido. Defina orçamento por
  módulo e por projeto; rode o QA e tarefas longas em outra ferramenta (Codex/Gemini/OpenCode) quando possível; deixe
  só Lead e Revisor em Opus.
- **Portas e bancos por projeto**: demo do projeto A em :8000, B em :8100…; bancos de demo/teste com prefixo do projeto.
- **Notas com prefixo**: "Painel · <Projeto>", "Log · <Projeto> · M<n>".

## D. Ritual de fechamento de módulo
1. Check completo verde e PR do módulo em docs/prs/.
2. Log do módulo fechado com totais de tempo/tokens/custo; Painel atualizado.
3. `/clear` em cada teammate (contextos de 300–500k tokens encarecem cada passo; o papel volta pelo
   --append-system-prompt-file e o estado pelos arquivos).
4. Reiniciar o servidor de demo se houve migration ou troca de settings (o reloader não sobrevive a INSTALLED_APPS).
5. PROGRESSO.md com o próximo módulo.

## E. Lições do piloto (o que deu errado e virou regra)
| Problema | Regra |
|---|---|
| `--role` prendeu agentes em .maestri/roles | recrutar com `--append-system-prompt-file` + `--dir` |
| Spec em YAML inválido | todo `texto:` em bloco `>`; validar com yaml.safe_load |
| 27 lacunas de spec ao longo do projeto | contrato completo (rotas, campos, códigos, mensagens, limites) antes do aceite |
| Índice git e banco de teste compartilhados | `git commit -- <paths>`, banco de teste por processo, floors |
| Agente formatou/reverteu arquivos alheios | format e checkout só nos próprios caminhos |
| Demo servindo código antigo; navegador com CSS velho | reloader ligado + estáticos `no-cache` + reinício após settings |
| Falso bug no portal (menu móvel) | provar comportamento em Playwright, portal só para ver |
| Linha clicável dependente do motor | soluções robustas (JS delegado) e teste por item |
| QA travado por erro de SSL da API | `recruit --replace` no lugar (mantém conexões e portais) |
| 2 paradas por cota (~2h50 + noite) | orçamento por módulo, /clear, PROGRESSO.md, QA fora do Claude se possível |
| Lead em Opus = 44% do custo | delegar investigação; menos imagens; Sonnet para rotina |
| Credencial de produção desconhecida | terminal de liberação onde o usuário digita a senha |
| Horários de log estimados à mão | sempre `date` ou commits |
| Revisor de segurança: 5 min, US$ 1,55, 2 falhas altas | revisor também no módulo anterior ao de risco |
