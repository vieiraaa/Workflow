# Roadmap · do piloto ao "n8n da casa" (M5–M8)

Proposta de 09/10/2026, a partir do pedido do usuário e do fluxo `Teste Workflow.json` (n8n, Digisac).
Status: **rascunho aprovado em parte** (D-021..D-024 em 09/10). Pendentes na seção 7 não bloqueiam o M5.

---

## 1. Ponto de partida (o que o motor tem hoje)

| Hoje (M2/M3)                                   | Limite que impede o "n8n"                                   |
|------------------------------------------------|-------------------------------------------------------------|
| 3 tipos de nó: gatilho, http, saida            | sem código, condição, e-mail, webhook, agendamento          |
| cadeia linear (GRF-03: 1 entrada / 1 saída)    | sem ramificação (IF/Switch) nem junção (Merge)              |
| `{{ anterior.x }}` só do nó imediatamente antes| o fluxo do Digisac usa `$('Config')`, `$('Contexto')` etc.  |
| saída = 1 objeto                               | n8n trabalha com **lista de itens** (560 chamados = 560 itens) |
| execução síncrona, 60 s, só manual             | agendamento e webhook exigem execução em segundo plano      |
| segredo digitado no header (mascarado depois)  | falta cofre de credenciais (token do Digisac)               |
| sem import/export                              | pedido: importar/exportar JSON igual ao n8n                 |

O que já está pronto e é reaproveitado: SSRF (SEG-01..08), mascaramento (SEG-09), histórico por nó,
desenho da execução (EXE-15), motor de permissão por setor (SET-06), Home com gráficos SVG.

---

## 2. Módulos propostos

### M5 · Motor v2 (o "coração n8n")
1. **Itens**: cada nó recebe e devolve uma lista de itens `[{json: {...}}]`; o nó roda 1x por item ou 1x no total
   (`executar_uma_vez`, igual ao `executeOnce` do n8n).
2. **Grafo com ramos**: várias saídas (IF: verdadeiro/falso; Switch: N saídas), várias entradas (Merge),
   execução em ordem topológica. Ciclo continua proibido (laço só pelo nó "Repetir em lotes").
3. **Expressões** `{{ ... }}` estilo n8n, com parser próprio (sem `eval` do Python):
   `$json.campo`, `$('Nome do nó').first().json.x`, `$('Nó').all()`, `$item`, `$now`, `$hoje`, `$execucao.id`,
   `$usuario.email`, `$credencial`, `$parametros.x` (entradas da Função, M7). Funções de texto/data/número em lista branca.
4. **Credenciais**: cofre cifrado (Fernet, chave só no ambiente), tipos *Bearer token*, *Header*, *Basic*, *SMTP*.
   O nó escolhe a credencial pelo nome; o valor nunca vai para grafo, histórico, export nem tela.
5. **Novos nós** (catálogo na seção 3).
6. **Paginação no HTTP** (modo "até a página vir com menos de N itens", limite de páginas). É o que o "Chamados do dia" usa.
7. **Importar/Exportar JSON**:
   - formato nativo (grafo canônico v2 + metadados; credenciais só por **nome**, nunca o valor);
   - **importar do n8n** (`nodes`/`connections`), com mapa de tipos e **relatório de importação**: o que entrou,
     o que precisa de ajuste (ex.: token embutido → "crie a credencial Digisac") e o que não tem equivalente;
   - exportar para n8n (melhor esforço, só nós com equivalente).
8. **Notas no canvas** (sticky notes), duplicar nó, copiar/colar trecho, desativar nó, "fixar dados" (pinData) para testar.

### M6 · Execução em segundo plano e gatilhos
1. **Fila em Postgres** (sem Redis): tabela de trabalhos + `manage.py trabalhador`. Roda manual, agendado e webhook.
   Execução manual continua com retorno imediato na tela (aguarda até X s; passou disso, vira "em andamento" com atualização ao vivo).
2. **Gatilho Agendamento**: intervalo (a cada N min/h), diário/semanal/mensal com hora, ou cron; fuso America/Sao_Paulo;
   mostra a próxima execução. Agendado executa como o **dono técnico** da Função (conta de serviço).
3. **Gatilho Webhook**: URL `/w/<id-aleatório>` com método, autenticação (token no header ou HMAC), limite de tamanho e de taxa.
   Nó **Responder ao webhook** (status, headers, corpo). Modo teste vs produção, como no n8n.
4. **Gatilho de Erro**: um fluxo "trata erros" roda quando outro fluxo falha (ex.: e-mail para o TI).
5. **Gatilho Formulário** (opcional): página com campos que dispara o fluxo.
6. **Retentativas por nó** (N vezes, espera) e "continuar em erro" (o `onError: continueRegularOutput` do JSON).
7. Limites: tempo por execução configurável por fluxo (padrão maior que 60 s no segundo plano), concorrência por fluxo.

### M7 · Tela **Funções**
Uma **Função** é um fluxo **publicado** para uso de todos, com cara de botão, não de canvas.

- **Catálogo** (cartões ou lista): nome, descrição, ícone, setor/visibilidade, **última execução** (quando, por quem, status),
  **próxima execução agendada**, botão **Executar** na linha, link para o último resultado.
- **Entradas** (parâmetros): o TI define campos (data, período, texto, lista, setor). Ex.: "Chamados do dia" pede `dia`
  (padrão: ontem). Quem executa preenche um formulário curto; vira `$parametros.dia` no fluxo.
- **Dois modos de execução** (pedido do usuário):
  - **Executar para mim**: qualquer usuário com acesso. O retorno vai **só para ele** (tela e histórico pessoal),
    filtrado pelo escopo dele (ver M8). Não altera nada que os outros vejam e não dispara envios gerais.
  - **Atualizar para todos**: só Adm/TI (e o agendador). Grava o **resultado oficial** da Função
    (o que alimenta painéis) e pode disparar os efeitos gerais (ex.: e-mail para a lista).
  - O TI marca no editor quais nós são **efeito geral** (ex.: e-mail para a diretoria); no modo "para mim" esses nós
    são pulados ou trocados pelo envio só ao próprio usuário.
- **Atividades em massa**: Função com entrada de planilha/CSV ou lista; executa item a item com barra de progresso e
  relatório de sucesso/erro por linha.
- **Publicação**: só Adm/TI cria, edita e publica Função; versão publicada é congelada (editar o fluxo não muda a Função até
  "Publicar nova versão"). Liberar para: todos, setores escolhidos ou papéis escolhidos.
- **Visualização rápida**: o último resultado oficial abre em tabela (ordenar, filtrar, exportar CSV) sem abrir o canvas.

### M8 · Integração Digisac / CSLog + painel de atendimento
1. **Credencial "Digisac"** (Bearer, base `https://eem.digisac.co`) no cofre.
2. **Função "Chamados do dia"**, importada do `Teste Workflow.json` e ajustada:
   gatilho Agendamento (todo dia 06:00) + Manual · `Config` vira **parâmetros** (dia) + credencial ·
   `Usuário do token` → `Contexto` → `Usuários` → `Chamados do dia` (HTTP com paginação) → `Lista de chamados` (Código)
   → **Gravar no conjunto de dados**.
3. **Conjuntos de dados** (tabela interna, versão simples do "Data Table" do n8n): a Função grava linhas com chave
   (`ticketId`), e as linhas ficam consultáveis por painéis. Reprocessar o mesmo dia **substitui**, sem duplicar.
4. **Vínculo usuário ↔ atendente**: cada usuário do sistema ganha o id/nome do atendente no Digisac
   (preenchido pelo Adm ou automaticamente pelo e-mail, via `/api/v1/users`).
5. **Painel de atendimento** (na Home ou aba própria), com escopo:
   - **Funcionário**: só os próprios chamados (por `atendenteDoChamado` = ele);
   - **Gestor**: a equipe (setor/departamento dele);
   - **Gerente e TI**: todos.
   Indicadores: chamados no dia/período, abertos x fechados, tempo médio de atendimento (`endedAt - startedAt`),
   por departamento, por atendente (ranking), por hora do dia. Mesmo padrão visual da Home (SVG, tabela equivalente).
6. **Executar para mim** no "Chamados do dia" traz só os chamados do próprio usuário; **Atualizar para todos** atualiza o painel geral.

---

## 3. Catálogo de nós (equivalência com o n8n)

| Grupo | Nó (nome no sistema) | n8n equivalente | Módulo |
|---|---|---|---|
| Gatilhos | Manual | Manual Trigger | já existe |
| | Agendamento | Schedule Trigger | M6 |
| | Webhook | Webhook | M6 |
| | Formulário | n8n Form Trigger | M6 (opcional) |
| | Erro de outro fluxo | Error Trigger | M6 |
| | Chamado por outro fluxo | Execute Workflow Trigger | M6 |
| Ações | Requisição HTTP (+ paginação, credencial) | HTTP Request | M5 |
| | Enviar e-mail (SMTP, HTML, anexo do resultado em CSV) | Send Email | M6 |
| | Responder ao webhook | Respond to Webhook | M6 |
| | Executar outro fluxo | Execute Workflow | M6 |
| | Gravar/Ler conjunto de dados | Data Table | M8 |
| Dados | Editar campos | Set / Edit Fields | M5 |
| | Código (JavaScript ou Python, isolado) | Code | M5 |
| | Filtrar | Filter | M5 |
| | Ordenar · Limitar · Remover duplicados | Sort · Limit · Remove Duplicates | M5 |
| | Separar lista em itens | Split Out | M5 |
| | Agregar · Resumir (contar, somar, média por grupo) | Aggregate · Summarize | M5 |
| | Data e hora | Date & Time | M5 |
| | Converter para CSV/planilha · Ler CSV | Convert to File · Extract from File | M7 |
| Fluxo | Se (IF) | If | M5 |
| | Escolher (Switch) | Switch | M5 |
| | Juntar (Merge) | Merge | M5 |
| | Repetir em lotes | Loop Over Items | M5 |
| | Esperar | Wait | M6 |
| | Parar com erro | Stop and Error | M5 |
| | Sem operação | No Operation | M5 |
| Saída | Saída / Resultado | (último nó) | já existe |
| Canvas | Nota | Sticky Note | M5 |

Fora do escopo (por ora): nós de IA/LLM, integrações prontas de terceiros (Slack, Google etc.). Tudo isso dá para fazer
com HTTP + credencial. Os nós prontos entram quando houver uso real.

---

## 4. Papéis e permissões (D-023: Gerente e TI separados; Adm continua)

Mapa: Base = funcionário · Coordenador = gestor do setor · **Gerente** (novo) · **TI** (novo) · Adm.
Proposta de divisão: o **TI** é o especialista técnico (cria Funções, Código, credenciais e integrações) e não administra
pessoas. O **Adm** administra usuários e setores e pode tudo. O **Gerente** vê tudo e não configura nada.

| Ação | Base | Coordenador | Gerente | TI | Adm |
|---|---|---|---|---|---|
| Ver Funções liberadas | sim | sim | sim | sim | sim |
| Executar Função **para mim** | sim | sim | sim | sim | sim |
| **Atualizar para todos** | não | *decidir* | *decidir* | sim | sim |
| Criar/editar/publicar Função | não | não | não | sim | sim |
| Fluxos (canvas) | executar ativos do setor | setor | ver todos | tudo | tudo |
| Nó Código, credenciais | não | não | não | sim | sim |
| Usuários e setores | não | não | não | não | sim |
| Painel de atendimento | os próprios | equipe | todos | todos | todos |
| Importar/Exportar JSON | não | exportar do setor | exportar | tudo | tudo |

Nó **Código** e **credenciais**: só TI e Adm (código roda no servidor; é a maior superfície de ataque do sistema).

---

## 5. Segurança (novas regras SEG a escrever)

- **Código isolado**: processo separado, sem rede, sem disco, sem variáveis de ambiente, limite de CPU/memória/tempo,
  entrada e saída só por JSON. Nunca `eval`/`exec` no processo do Django.
- **Credenciais**: cifradas em repouso; mascaradas em entrada/saída/snapshot/export; troca de valor sem revelar o antigo.
- **Webhook**: id aleatório longo, autenticação obrigatória em produção, limite de corpo e de taxa, CSRF isento só nessa rota.
- **E-mail**: destinatários em lista branca de domínios (ex.: `@eem.adv.br`) ou aprovados pelo TI; limite por execução.
- **Importação**: o JSON do n8n passa pela mesma validação fechada do grafo (GRF-09); código importado fica **desativado**
  até um Adm revisar; tokens encontrados em texto viram alerta "mova para uma credencial".
- **"Para mim"**: o filtro de escopo do resultado é aplicado **no servidor**, depois da execução e antes de gravar ou mostrar.
- SSRF continua valendo para todo HTTP, inclusive paginação e redirects.

---

## 6. Ordem sugerida e tamanho

| Módulo | Entrega visível | Esforço relativo |
|---|---|---|
| M5 Motor v2 | importar o `Teste Workflow.json` e rodá-lo manualmente | maior (motor e editor mudam) |
| M6 Segundo plano + gatilhos | "Chamados do dia" roda sozinho às 06:00; webhook; e-mail | médio |
| M7 Funções | tela Funções com executar na linha, última/próxima execução, para mim × para todos | médio |
| M8 Digisac + painel | painel de atendimento por funcionário/equipe/todos | médio |

Atalho possível: um **M5-mínimo** (itens + `$('Nó')` + Código + credencial + paginação + importar n8n) já roda o fluxo do
Digisac. IF/Switch/Merge e o resto do catálogo podem vir na sequência.

---

## 7. Decisões

Tomadas em 09/10:
- **D-021 · Nó Código em JavaScript**, como no n8n, em runtime JS isolado (fora do processo do Django). O código do
  `Teste Workflow.json` entra sem reescrever.
- **D-022 · CSLog ≠ Digisac**. São sistemas diferentes: o Digisac já tem o fluxo pronto; o CSLog tem API própria e
  **precisa da documentação ou de um exemplo de requisição/resposta** para virar Função.
- **D-023 · Papéis Gerente e TI separados**, e o Adm continua (divisão da seção 4, a confirmar).
- **D-024 · Ordem: M5 completo primeiro** (catálogo inteiro de nós), depois M6, M7 e M8.

Ainda abertas (não bloqueiam o M5):
- **D-d · "Atualizar para todos"**: além de TI/Adm, Gerente e/ou Gestor (no escopo deles)?
- **D-e · Vínculo funcionário ↔ atendente do Digisac**: pelo e-mail (automático) ou cadastro manual?
- **D-f · E-mail**: servidor SMTP (Microsoft 365? Google?) e domínios que podem receber.
- **D-g · Webhook público**: o servidor fica acessível de fora ou só na rede interna?
- **D-i · Runtime JS**: Node.js instalado no servidor (processo isolado por execução) ou motor embutido (QuickJS);
  a escolha vem com prova de isolamento do Atalaia.
- **CSLog**: documentação da API.

Pendentes herdados do M4: SET-07 (a), vínculo dos usuários reais aos setores, `docs/ENTREGA.md`, tags de versão.
