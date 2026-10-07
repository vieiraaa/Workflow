# M1 · Usuários e papéis (branch feat/modulo-1)

## Entregue
| Tarefa | Dono | Commit | Ciclos | Resumo |
|---|---|---|---|---|
| T-003 | Lupa | fb09194, 53bb49a | 1 | 121 testes de aceite só pela spec |
| T-004 | Forja | a6eaf0f | 1 | Lista de usuários: busca, filtros, ordenação, paginação, queries constantes |
| T-005/T-006 | Forja | f9b403b, 30700f8 | 2 | Criar, editar, redefinir senha, trocar a própria senha, sessão de inativo |
| T-007 | Vitral | f5beeb6, 8a69c8d, 2d7c1c0, 317db06, 52985f2 | 2 + 1 rodada visual | Templates TEL-02/03/08/09, 403 sem papel com "Sair" |
| T-008 | Lupa | 42d8c4a | 1 | 103 ataques adversariais, 2 achados |
| T-009 | Forja | f37cbb4 | 1 | Correções: NUL na busca → 500; sessão de desativado |

## Check completo
`python scripts/check.py --modulo 1`: ruff, format, makemigrations, SEG-08, pytest (330 testes: unit + aceite m1 +
adversarial m1, cobertura 98%), pip-audit, telas (console/overflow 390px) → VERDE.

## Revisão visual
- Rodada 1: 4 altas (tabela cortada a 390px; sidebar sem altura total; toggle sem erro por campo; Trocar senha sem caminho na UI).
- Rodada 2: 0 altas. Média pendente: select de papel nativo (fica para o designer).
- Capturas: docs/telas/m1/ (TEL-02, 03, 08, 09 × light/dark × 1440/390).

## QA adversarial
Barrados: IDOR/escalada em todas as rotas, mass assignment, auto-proteção do último Adm, CSRF, XSS (lista, edição, menu,
toasts), entrada hostil, open redirect, enumeração de e-mail, logout GET. Achados corrigidos: `?q=%00` → 500 e sessão de
usuário desativado não encerrada (T-009). Fora do escopo: rate limit de login (D-012).

## Decisões
D-011 senha com 5+ caracteres distintos (vinha de um teste além da spec; incorporado em USR-04) · D-012.

## Edições em aceite
Só pelo próprio QA, após o Lead fechar lacunas da spec (USR-13..15). Nenhuma edição por construtor.

## Observações
- Rotas `fluxos:lista` e `execucoes:lista` são placeholders (o aceite do M1 faz reverse delas); M2/M3 substituem.
- Aceite do M2 já escrito (T-010, 165 testes, marcados m2).

## Custo estimado (API) até o fecho do M1
Ver nota "Log de Atividades" e `python3 docs/metricas/metricas.py`: time ≈ US$ 14,5 (≈ 96% da entrada é leitura de cache).
