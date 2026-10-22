---
name: design-base
description: Identidade visual Egger e Mesquita v2 do Construtor de Workflows (lateral ameixa nos dois temas; claro lilás-claro e escuro ameixa profundo; roxo, ouro e ameixa da marca; Montserrat + IBM Plex Sans/Mono), com tokens, componentes, ícones e checklist de revisão visual. Carregue antes de criar ou alterar qualquer template, CSS ou tela, e na revisão visual de cada módulo.
---

# Design base: identidade Egger e Mesquita v2 (D-038, substitui a paleta da D-036)

Produto interno de um escritório de advocacia de massa: **mesa de controladoria**: profissional, sóbria, densa de
informação, sem ornamento. Toda decisão visual mora em `tokens.css` (nesta pasta, copiado para `static/css/tokens.css`)
e nos componentes de `templates/componentes/`. Os NOMES dos tokens são estáveis: mude valores, não nomes.

## Referências
- **Guia e prévia aprovados (22/10):** `~/Downloads/Agente de IA para Prazos e Cadastro/previa-identidade/IMPLEMENTACAO-PAINEL.md`
  e `painel-v2.html`. Os anteriores (`painel.html`, `painel-*.png`) ficam só como histórico.
- **Marca:** roxo `#4F1F5C` (letras do logo), ouro `#F8B334` (o "e"), ameixa `#3E2745` (fundo da versão negativa).
  Logos e emblema oficiais em `static/img/marca/`.

## Regras de cor
- **A lateral é sempre ameixa**, nos dois temas (`--sidebar`, textos `--lat-*`). É o lugar de maior presença da marca.
- **Claro:** fundo `#F6F4F8`, painéis brancos, primário **roxo**.
- **Escuro:** **ameixa profundo**, derivado da versão negativa do logo (fundo `#17101C`, painéis `#211827`), primário
  **ouro** com texto escuro.
- Texto sobre `--accent` usa SEMPRE `--on-accent`.
- **Dourado é da marca e das ações** (emblema, item ativo da lateral, foco, botão primário no escuro, folha da
  audiência), **nunca de status**.
- **Status:**

  | Status | Token |
  |---|---|
  | Cadastrado | `--success` |
  | Conferir | `--conf` (azul) |
  | Com pendências / campo faltando | `--pend` |
  | Erro | `--danger` |

  Cada um tem `--fill-*` para o fundo do chip.
- Não ponha texto `--pend` sobre `--surface-2` (contraste 4,4:1).
- Foco de teclado: contorno dourado de 2px (`:focus-visible`).

## Tipografia e ícones
| Papel | Fonte | Onde |
|---|---|---|
| Marca | Montserrat 600 | título da página (26px), títulos de painel e de grupo, nome na lateral |
| Texto | IBM Plex Sans 400/500/600 | todo o resto (substitui a Inter) |
| Números | IBM Plex Mono 400/600 | número CNJ, contagens, dia da audiência, valores alinhados |

- Fontes vendorizadas (OFL) em `static/vendor/<fonte>/<versao>/`. Nada de Google Fonts em runtime.
- Rótulos em **caixa normal**: sem CAIXA ALTA espaçada.
- Números com `font-variant-numeric: tabular-nums`. Base 14px.
- **Ícones:** Lucide (ISC), sprite em `static/vendor/lucide/<versao>/`, traço 1.6–1.75, 18–20px na UI, via
  `componentes/icone.html`.
- **Formato brasileiro:** datas DD/MM/AAAA (HH:MM), dinheiro R$ 1.234,56. Nunca ISO na tela.

## Componentes
- **Shell:** lateral de 236px ameixa com:
  - emblema dourado redondo e "Workflows / Egger e Mesquita";
  - seções em Montserrat 600, caixa normal;
  - itens com ícone de linha, em `--lat-texto-2`;
  - **item ativo** com fundo `--lat-ativo-fundo` e texto `--ouro`, **sem barrinha lateral**;
  - rodapé com o usuário e o botão de tema.

  Topo da página: título, subtítulo (`--text-3`, "Atualizado às HH:MM") e ações à direita. Abaixo de 900px, a lateral
  vira barra no topo, só com ícones, exceto o item ativo.
- **Fluxo / esteira** (painéis de processo; substitui cartões de KPI soltos):
  - bloco de entrada com ponto dourado pulsando para "em leitura";
  - barra em escala, um segmento por etapa, com largura proporcional;
  - etapas clicáveis (`button` com `aria-pressed`): número em `--font-num`, nome na cor do status e legenda curta.
- **Painel:** `--surface`, borda `--hairline`, raio `--r-l`, `--shadow-1`; título Montserrat 600 13px, com complemento à
  direita em `--text-3`.
- **Lista selecionável:** item `button`; selecionado com `--fill-accent` e `aria-current`; hover `--surface-2`.
- **Linhas rótulo → valor:** rótulo `--text-2`, valor à direita (peso 500), separador `--hairline`. Valor faltando:
  "não encontrado no PDF" em `--pend`, com sublinhado tracejado.
- **Botões:**
  - primário: `--accent` com `--on-accent`;
  - secundário: `--surface` com borda `--borda-forte`;
  - filtro ativo: `aria-pressed`, com borda `--accent`.

  Altura de cerca de 34px, raio `--r-m`, peso 600, 13px.
- **Campos:** fundo `--surface-2`, borda `--hairline`, raio `--r-m`, foco dourado; label acima, erro abaixo em `--danger`.
- **Chips de status:** pill com fundo `--fill-<status>` e texto na cor do status.
- **Estado vazio, toast, modal** (raio `--r-xl`), **bloco de código** (`--font-mono`, `--surface-2`).
- **Gráficos:** séries nas cores de status; eixos e grade em `--hairline`; legenda em `--text-2`.
- **Nó do canvas:** card com ícone em quadrado colorido por tipo, título, resumo de uma linha e badge de erro.

## Movimento
Transições de 150 a 200ms com `--ease`. O pulso do "em leitura" para com `prefers-reduced-motion`.

## Checklist da revisão visual (capturas light E dark, 1440 E 390)
Severidade **alta** (corrigir antes de fechar o módulo):
- [ ] Tela sem o shell ou com a lateral fora do ameixa; cara de HTML padrão.
- [ ] Cor, raio, sombra ou tamanho fora dos tokens; `#fff` fixo sobre `--accent`; contraste abaixo de AA.
- [ ] Dourado usado como cor de status; identidade de terceiros.
- [ ] Falta o estado vazio, de erro ou de carregando.
- [ ] Overflow horizontal ou sobreposição em 390px.
- [ ] Formulário sem label, sem erro por campo ou sem foco visível; controle clicável que não é `button`/`a`.
- [ ] Data em ISO ou dinheiro fora do formato brasileiro.
Severidade **média**:
- [ ] Título ou rótulo fora da Montserrat; número fora da IBM Plex Mono ou não tabular; CAIXA ALTA espaçada.
- [ ] Espaçamento fora da escala de 4px; ícones de tamanhos misturados.
- [ ] Hierarquia fraca (o título não se destaca; a ação principal não é óbvia).
