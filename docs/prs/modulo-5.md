# M5 · Motor v2 (itens, expressões, credenciais, nó Código, importação n8n) — branch `feat/modulo-5`

Pedido do usuário (09/10/2026): "Iniciar o M5 completo" do `docs/ROADMAP-n8n.md` (D-024). Meta do módulo: o fluxo n8n
"Chamados do dia" (Digisac) importado e executando no sistema.

## O que entra
- **Motor v2 com itens** (MV2-01..25): cada nó recebe e devolve uma lista de itens; ordem topológica; execução por item;
  contagem entrada→saída por nó; desativar nó; limites de itens, de tamanho e de tempo; texto persistido truncado com marca.
- **Expressões v2** (D-025): `{{ $json… }}`, `$node["X"]`, optional chaining `?.`, funções de texto/data seguras; sem `eval`.
- **Paginação HTTP** com enum validado (formato inválido = 400) e corte por `resposta_grande`.
- **Credenciais** (CRD-01/02): cofre Fernet (`cryptography`, D-026), tipos bearer/básico/cabeçalho; valor nunca volta
  à tela (campo em branco = manter); escopo por setor; o nó HTTP referencia a credencial pelo nome.
- **Nó Código** em JavaScript (D-021/D-027): Node 24 fora do processo do Django, `--permission`, env vazio, `vm` sem
  objetos do host e SEGUNDA parede de rede do SO (sandbox-exec no macOS, `unshare --net` no Linux; sem camada = recusa).
- **Importação n8n** (IMP-01..06): mapeia nós suportados, relatório (importados, ajustes, segredos, sem equivalente,
  código desativado, expressões não suportadas); segredo detectado NÃO é gravado; nós Código entram desativados até revisão.
- **Detector de segredos no grafo inteiro** e **mascaramento por valor de todo dado gravado** (SEG-17..21, MV2-25).
- **Detalhe da execução v2** (EDV-01..03, NOV-01..06): itens por nó, requisições, logs mascarados.

## Testes
- Aceite M5 (Lupa, só pela spec): 620/620. Adversarial M5: 373/373 após 5 defeitos achados e corrigidos (T-066).
- Revisão de segurança (Atalaia, T-058): 1 achado, corrigido.
- Check completo (13/10): **VERDE** — ruff, format, makemigrations, SEG-08, pytest (3.419 testes), telas, pip-audit.
- Prova real (13/10, demo local): o "Teste Workflow" do usuário importado → credencial "Digisac" → execução #696
  sucesso contra o Digisac real (4 chamados); token ausente em todo dado gravado.

## Revisão visual
52 capturas em `docs/telas/m5/`; rodada 2: 0 altas. Médias para o designer: nó "Resultado" cortado na borda do canvas;
rótulos pequenos no desenho em 390 px.

## Para revisar no PR
- `apps/motor/` (executor v2, expressões, paginação, nó Código, mascaramento), `apps/credenciais/` (cofre),
  `apps/fluxos/importacao*` (n8n), migrations `credenciais 0001`, `execucoes 0003`, `fluxos 0003/0004`.

## Implantação (após o merge)
1. O usuário adiciona `CREDENCIAIS_CHAVE` (chave Fernet) ao `.env` — sem ela o cofre recusa salvar credenciais.
2. Aplicar as migrations no Supabase — só com OK do usuário.
3. Atualizar a cópia estável (`../construtor-workflows-estavel`, D-018) e reiniciar o servidor Supabase em :8000
   (hoje a :8000 está com o demo).
4. Servidor de produção: o nó Código só roda em macOS/Linux com isolamento de rede (D-027).

## Pendências do usuário
SET-07 (a) · melhorias da nota "Melhorias · Ollama" · decisões D-d..D-i do roadmap · M6–M8.
