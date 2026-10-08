# M2 · Fluxos + editor de canvas (branch feat/modulo-2)

## Entregue
| Tarefa | Dono | Commits | Ciclos | Resumo |
|---|---|---|---|---|
| T-010 | Lupa | 5076227, 3d9ce73, 378f39a, 83a6f0c | 2 | Aceite M2 (165 + 65 de GRF-09) só pela spec |
| T-011 | Forja | 00d538f | 1 | Servidor de demo local isolado (sem .env/Supabase) |
| T-012 | Lupa | b7962b3, af66a2a | 1 | Portais de visualização iOS 390 / Android 412 / Windows 1440 + teste do menu (chromium+webkit) |
| T-013 | Forja | 6649e44 | 3 | Model Fluxo + validador do grafo (formato x pendência) |
| T-014/T-015 | Forja | 5f855f9, 42e2d79 | 1 | Lista, CRUD, status, editor, salvar_grafo (400/409/pendências, EST-01) |
| T-016 | Vitral | e857bcc | 1 | Lista de fluxos (TEL-04/12), modais |
| T-017 | Vitral | 4189c9d, dcb7993 | 2 | Editor de canvas (Drawflow 0.0.60), inspector, toolbar, e2e Playwright |
| T-018 | Vitral, Forja | 420882c, 63d6d60 | 2 | Select estilizado, aria-label, enquadramento do editor, 500 do produto |
| T-019 | Forja | 964d69b | 2 | Demo com DEBUG=False (404/500 do produto nos portais) |
| T-020 | Lupa | 11ca3a7 | 1 | Adversarial M2: 126 ataques, 6 achados |
| T-021 | Forja | 68d74ae | 2 | JSON hostil no salvar_grafo → 400 (GRF-09) |
| T-022 | Forja | a680dd3 | 1 | Banco de teste por processo (contenção entre agentes) |

## Check completo
`python scripts/check.py --modulo 2` → VERDE: ruff, format, makemigrations, SEG-08, pytest (821 testes, cobertura 98%),
pip-audit, telas (console/overflow 390px). Conferido também: e2e canvas + aceite m2 + adversarial m2 = 360 verdes com
banco isolado após o schema fechado.

## Revisão visual
- Rodada 1: 1 alta (editor não enquadrava o grafo ao abrir), 1 média (sem 500 do produto), 1 baixa (faixa sob o canvas).
- Rodada 2: 0 altas. Média para o designer: a 390px o editor alinha ao 1º nó e o 3º exige arrastar.
- Portais (T-012): menu móvel "não abria" = artefato do portal (documento oculto pausa transições no WebKit), não bug (D-014).
- Capturas: docs/telas/m2/ (TEL-04, 05, 12 × light/dark × 1440/390).

## QA adversarial
Barrados 120/126: IDOR/escalada, mass assignment, CSRF, Content-Type, 5 MB, ids hostis e __proto__, ciclos, corrida
(200/409), replay, status forjado, placeholders hostis gravados sem avaliar, XSS no canvas e inspector (chromium e webkit).
Achados corrigidos (T-021): NaN/Infinity/1e999, surrogate solto, aninhamento de 100 mil níveis → todos davam 500.

## Spec e decisões
FLX-06 (rotas/campos), GRF-08 (lacunas do aceite), GRF-09 (schema fechado, profundidade 16, números finitos, UTF-8).
D-013 portais · D-014 menu nos portais · D-015 Drawflow.

## Edições em aceite
- test_base_nao_ve_rascunho_nem_por_busca_filtro_ou_paginacao (Lupa, 378f39a): checava "Oculto" cru e a busca ecoa o
  termo no campo; agora checa os nomes dos fluxos ocultos — prova o mesmo PRM-04 sem falso positivo. Defeito apontado pelo
  Forja sem editar o teste; confirmado pelo Lead.

## Time
- Cota parou o time 1x (~12:00 → 14:20); estado retomado por PROGRESSO.md sem perda.
- Contenção do banco de teste entre agentes → T-022.
- Custo estimado acumulado (API) ao fechar o M2: ~US$ 41 (python3 docs/metricas/metricas.py).
