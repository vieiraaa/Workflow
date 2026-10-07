# Fase 0 · Arranque (branch feat/modulo-0)

## Entregue
- T-001 (Forja, 7523615): Django 5.2 + Py 3.14, settings base/dev/teste, trava anti-Supabase em teste,
  Usuario custom (login por e-mail), Groups dos papéis por migration, motor `permissoes.py` lendo a spec,
  login/logout, 403/404 do produto, `semear_demo`, `scripts/check.py`, `scripts/telas.py`. 2 ciclos.
- T-002 (Vitral, ae82eda): tokens, app.css/app.js, shell (sidebar, topbar, tema, toasts, menu mobile),
  15 componentes, Inter 5.3.0 e Lucide 1.52.0 vendorizados, login, início, 403/404. 2 ciclos.
- T-003 (Lupa, fb09194 + 53bb49a): 121 testes de aceite do M1 a partir só da spec (vermelhos por design).
- Lead: CLAUDE.md, DECISOES.md (D-001..010), spec completa (7 arquivos), tarefas T-001..T-007.

## Check
`python scripts/check.py --modulo 0`: ruff, format, makemigrations, SEG-08, pytest+cobertura (55 unit),
pip-audit, telas (console/overflow 390px) → VERDE.

## Revisão visual (rodada 1)
Capturas em docs/telas/m0/ (TEL-01, 10, 11 × light/dark × 1440/390). Alta: 0.
Média: 403 de usuário sem papel oferece "Ir para o início" (volta ao 403) → trocar por "Sair" (T-007).

## Achados do processo
- `--role` do Maestri iniciava os agentes em .maestri/roles/<id>/ (sem .claude/); corrigido (D-006).
- Spec com YAML inválido (achado pelo Forja); corrigido (D-010).
- Forja rodou `ruff format` amplo e reverteu com `git checkout` arquivos do QA/Front; verificado sem perda
  (diff vazio contra os commits deles). Regra reforçada: format só nos próprios caminhos.

## Edições em aceite
- T-003 ajustado pelo próprio QA após o Lead fechar lacunas da spec (USR-13..15). Nenhuma edição por construtor.
