# Nó "Chamar n8n" — branch `feat/no-chamar-n8n`

Pedido do usuário (14/10/2026): chamar um fluxo que já existe no n8n pelo webhook, sem trazê-lo para cá.
Spec: `docs/spec/no-n8n.yaml` (N8N-01..07). Decisão: D-032.

## O que entra
- **Nó novo na paleta** (`chamar_n8n`): URL do webhook, método POST/GET, credencial opcional, o que enviar (item,
  todos os itens ou corpo personalizado com expressões), "Aguardar resposta" (padrão sim) e tempo limite de 1 a 55 s.
- **Feito sobre o cliente HTTP do motor**: mesma proteção SSRF/pin, mascaramento de segredos e limites. Não há
  caminho de rede novo. Um n8n em endereço interno continua bloqueado (D-032).
- **Pendências e aviso no editor** (N8N-02/07): URL vazia ou sem http(s), corpo vazio e tempo fora de 1..55 bloqueiam a
  execução. Uma URL `/webhook-test/` gera só um aviso: ela funciona apenas com o n8n em "Listen for test event".
- **Resposta → itens** (N8N-04): uma lista vira um item por elemento; um objeto vira um item; corpo vazio vira
  `{n8n_status}`; texto vira `{resposta}`. Com "Não aguardar resposta", os itens de entrada seguem adiante com
  `n8n_status` (o nó lê no máximo 64 KB).
- **Erros em português claro** (N8N-05): 404 (webhook não encontrado ou fluxo inativo), 401/403 (credencial), outros
  status e tempo esgotado, com a dica "Não aguardar resposta" para fluxos longos.

## Testes
- Aceite (Lupa, escrito só pela spec): 78 verdes, contra um n8n falso local.
- Adversarial: SSRF por expressão e por redirect, JSON aninhado e enorme, header injection, credencial refletida,
  limite de 64 KB e query hostil no GET. Achou **1 defeito real**: JSON com milhares de níveis causava
  RecursionError e o nó não era gravado. Corrigido em T-076: o nó agora termina com erro `resposta_invalida`
  "A resposta do n8n é aninhada demais (mais de 100 níveis).".
- Check completo (19/10, com o T-076): **VERDE**. Inclui ruff, format, makemigrations, SEG-08, pytest com cobertura, pip-audit e telas.

## Para revisar no PR
`apps/motor/nos/n8n.py`, `apps/motor/http.py` (limites por chamador e profundidade), `apps/fluxos/` (validação e
avisos), `static/js/canvas/` (paleta, inspector, resumo), `templates/fluxos/editor.html`.

## Implantação
Sem migração. Para um teste real, faltam o domínio do n8n do escritório e uma credencial do webhook, que o próprio
usuário cadastra.
