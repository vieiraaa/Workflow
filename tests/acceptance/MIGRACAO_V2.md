# Migração dos testes M2/M3 para o contrato v2 (T-060)

Regra de ouro: atualizar, não apagar. Nenhum teste foi removido; os que testavam comportamento revogado pela spec foram
**convertidos** em teste do novo comportamento (regra citada na docstring). Garantias de segurança iguais ou mais fortes.

## Fixtures (afetam todos os testes de M2/M3 e adversariais)
| Arquivo | Mudança | Regra |
|---|---|---|
| acceptance/conftest.py, adversarial/conftest.py | `grafo_minimo_valido` em versao 2; `grafo_valido_v1` novo (prova da migração) | MV2-02, MV2-03 |
| idem `fabrica_fluxo` | fluxo nasce no setor "Geral" (Coordenador do setor enxerga) | SET-01, SET-04, SET-06 (drift do M4) |
| acceptance/m3/conftest.py, adversarial/m3/conftest.py | `cadeia`/`cfg_http`/`_no` em v2; HTTP com `resposta_completa=true` (como a migração marca) | MV2-02, MV2-12 L1, MV2-14 (1) |
| adversarial/m3/conftest.py | rotas novas `/reflete`, `/status-xss` | SEG-21, MV2-22 |

## Aceite M2
| Teste | Mudança | Regra |
|---|---|---|
| test_fluxos_crud::test_criar_fluxo_sucesso | grafo novo versao 2 (+notas) | MV2-02/03 |
| test_fluxos_crud::test_ativar_com_pendencias_json_400, test_est01_salvar_grafo_com_pendencia_derruba_ativo | gatilho sozinho/sem Saída não é pendência; usa nó solto | MV2-12 L4 |
| test_fluxos_crud (vazio/ativo→rascunho) | seeds em v2 | MV2-02 |
| test_grafo::FORMATO[versao_2] | → `versao_3`, `versao_0`, `versao_texto` (400); v2 válida | MV2-12 L3 |
| test_grafo::FORMATO[aresta_*_inexistente] | saem do formato (400) e viram `test_ligacao_para_no_inexistente_e_pendencia` (200 + pendência); entram `aresta_saida_negativa`, `em_erro_invalido`, `nota_cor_invalida`, `dados_fixos_nao_objeto`… | MV2-12 L3, MV2-02 |
| test_grafo::test_payload_acima_de_256kb_400 | → `..._acima_de_2mb_400_e_entre_256kb_e_2mb_aceito` | MV2-02 |
| test_grafo::test_mais_de_50_nos | → `test_mais_de_200_nos_400_e_200_aceito`; novos limites de arestas (400), notas (100), texto da nota (5000) | MV2-02 |
| test_grafo::PENDENCIAS | `sem_saida`, `duas_saidas_de_um_no`, `duas_entradas_em_um_no` → `NAO_PENDENCIAS` (`test_v2_nao_e_mais_pendencia`: salva sem pendência e ativa); `dois_gatilhos` = "exatamente 1 gatilho"; novos: `titulo_duplicado`, alça inexistente, `dados_fixos_de_no_inexistente` | MV2-12 L4, L3; MV2-14 (6) |
| test_grafo::test_pendencia_aponta_o_no | pendência global (no=None) agora é "sem gatilho" | MV2-12 L4 |
| test_grafo::CONFIG_INVALIDA/VALIDAS (corpo) | `corpo` string → `{"tipo","conteudo"}`; placeholder `anterior.x` → `$json.x` | MV2-14 (1), MV2-03 |
| NOVOS test_grafo | `test_salvar_v1_converte_e_grava_v2`, `..._reescreve_anterior_e_marca_resposta_completa`, `test_editor_abre_grafo_v1_ja_convertido`, `test_salvar_v2_valido_continua_aceito` | MV2-03, MV2-12 L1/L3 |
| test_grafo_formato_fechado (ONDE=corpo; seeds; DESCONHECIDAS) | corpo v2; chaves desconhecidas também em nota, tamanho e corpo | MV2-02, GRF-09 |

## Aceite M3
| Teste | Mudança | Regra |
|---|---|---|
| test_execucao::test_formato_gravado_do_no_http | entrada = lista de itens; requisição em `requisicoes[]`; resposta em `requisicoes[].resposta` | MV2-12 L2, MV2-15 B10, MV2-22 |
| test_execucao (métodos, corpo texto, gatilho, falha_mantem, saida) | `saida[0]["json"]` | MV2-12 L1/L13 |
| test_execucao::test_http_4xx_5xx... | status/headers/corpo do erro lidos de `requisicoes[].resposta` | MV2-22 (EXE-06 sem regressão) |
| test_execucao (resposta grande, gzip, limite por setting) | marca de truncamento: `ExecucaoNo.truncado` ou `resposta.truncado` | SEG-07, MV2-12 L2, MV2-22 |
| test_execucao::test_pendencias_nao_criam_execucao | grafo vazio v2 | MV2-02 |
| test_mascaramento (headers/query/placeholder) | "entrada gravada" → `requisicoes[]` | SEG-09, MV2-15 B10 |
| test_mascaramento::test_headers_sensiveis_da_resposta... | saída + `requisicoes[].resposta.headers` | SEG-09, MV2-22 |
| test_mascaramento::test_segredo_refletido_no_corpo_da_resposta_nao_e_mascarado | **INVERTIDO** → `..._e_mascarado_por_valor` (header, query e query da url; saída, resposta, tela); novo `test_mascara_por_valor_so_a_partir_de_4_caracteres` | SEG-21 (substitui SEG-16 item 6) |
| test_placeholders (todos) | `anterior.x` → `$json.x`; `headers.x-marcador` → `$json.headers['x-marcador']`; `lista.1` → `lista[1]` | MV2-03, MV2-10 |
| test_placeholders::caminho_inexistente / indice_fora / descida_em_escalar | erro `placeholder` → `''` sem erro; propriedade DE undefined → erro `expressao` (testes novos separados) | MV2-12 L8(d)(e) |
| test_placeholders::parser_proprio | `{{ 7*7 }}` deixa de ser "literal": agora = "49" (`test_aritmetica_e_avaliada...`); injeções seguem `expressao`/vazio | MV2-10 |
| test_placeholders (entrada gravada) | `requisicoes[0].query` | MV2-15 B10 |
| test_ssrf (redirect, host por placeholder) | `saida[0]["json"]`, `$json.corpo.host` | MV2-12 L1, MV2-03 |
| m5/test_m5_motor_itens (extra T-060) | nó `falhas` ligado ao `d` quando não há alça (evita "nó solto") | MV2-12 L4 |
| m5/test_m5_importacao (edição pedida, Task T-051) | Adm sem setor criado no teste; `or True` trocado por verificação real (dono = quem importou); setor esperado = o de quem importou | SEG-19/C6/C8 |

## Adversarial
| Teste | Mudança | Regra |
|---|---|---|
| m2: json gigante, aninhado, NaN, surrogate, chave duplicada | payloads em v2; gigante = 5 MB em `dados_fixos` (limite 2 MB, tipo correto) | MV2-02 |
| m2: arestas duplicadas/auto/ciclo | v2; duplicada só não pode 500 | MV2-12 L4 |
| m2: cadeia de 50 → 200 nós | | MV2-02 |
| m2: PENDENTES (`so_gatilho` → `no_solto`) | | MV2-12 L4 |
| m2: placeholders hostis | corpo v2; novos `$json.__proto__`, `constructor.constructor(...)`, `$('x')` | MV2-10 |
| m2: placeholder fora de string | → aceito no v2; JSON inválido sem placeholder segue pendência | MV2-15 B6 |
| m2: XSS no editor (browser) | grafo v2 com nota e dados_fixos hostis | SEG-13, MV2-02 |
| m2 NOVOS | versao hostil (True, "1", 2**63…), v1 hostil, XSS em nota/dados_fixos no HTML, IDOR Base × dados_fixos, chave hostil em dados_fixos no editor | MV2-12 L3, SEG-13, PRM-02 |
| m3: placeholders (`anterior` → `$json`), categoria `expressao` na lista fechada | | MV2-03, MV2-12 L12 |
| m3: segredos (blobs incluem `requisicoes`); eco de headers não pode refletir o segredo | mais forte | SEG-21, MV2-22 |
| m3: resposta infinita / gzip-bomba | `saida[0]["json"]["corpo"]` + marca truncado | SEG-07 |
| m3 NOVOS | segredo refletido em header+corpo mascarado; erro 5xx com HTML escapado na tela; corpo gravado ≤ 8 KB | SEG-21, MV2-22, SEG-13 |

## Removidos
Nenhum teste removido.
