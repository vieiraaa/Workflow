# Progresso (sobrescrito a cada resultado) — 13/10
M5 em 63997a6; M7a em 8538c94.
Main = 8538c94 (M7a integrado e no GitHub, 13/10) · branch atual feat/modulo-7a
Demo :8000: Função "Chamados do dia" publicada (exec #699 ok)
Pendente do usuário: CREDENCIAIS_CHAVE no .env + OK p/ migrations M5/M7a no Supabase · D-d · SET-07 (a) · Melhorias · Ollama · M6
Servidores: :8000 = demo local · Métricas: python3 docs/metricas/metricas.py

## 19/10/2026
- Nó "Chamar n8n" (branch feat/no-chamar-n8n): aceite 78 + adversarial; 1 defeito real (JSON aninhado → RecursionError)
  corrigido em T-076 (de6dfed); check completo VERDE; PR em docs/prs/no-chamar-n8n.md. Merge na main só a pedido do usuário.
- M8 · Jurídico · Cadastro de processos (substitui n8n + Excel + Power Apps): spec docs/spec/juridico-cadastro.yaml
  (CAD-01..22, CAD-07a; TEL-27..35), tarefas T-077..079, branch feat/m8-cadastro (a partir de feat/no-chamar-n8n).
  Testes reais (Dify interno, rede oficial) no notebook da empresa após o git; no Mac só Dify/DataJud falsos.
- M8 FECHADO (19/10): aceite + adversarial (8 achados corrigidos em T-083) + T-081/082 (revisão visual) + T-084/085
  (serialized_rollback nos adversariais) · check completo VERDE · 96 capturas em docs/telas/m8 · PR em
  docs/prs/modulo-8.md (com roteiro de teste no notebook). Merge na main só a pedido do usuário (leva junto o nó n8n).
  Demo agora em :8001 (8000 fica para a cópia estável/Supabase, D-018). Notas de log compiladas numa só ("Log de Atividades").

## 20/10/2026
- Identidade visual Egger e Mesquita (branch feat/identidade-eem, sobre feat/m8-cadastro): design-base nova, todas as telas, papel do Vitral reescrito; T-086..089; check completo VERDE; 336 capturas; PR em docs/prs/identidade-eem.md. Merge/push só a pedido. Pendente do usuário: logo negativo PNG transparente.
