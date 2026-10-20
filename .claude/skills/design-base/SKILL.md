---
name: design-base
description: Identidade visual Egger e Mesquita do Construtor de Workflows (escuro azul-marinho quase preto e claro com a mesma base; roxo, ouro e ameixa da marca; Montserrat + Inter), com tokens, componentes, ícones e checklist de revisão visual. Carregue antes de criar ou alterar qualquer template, CSS ou tela, e na revisão visual de cada módulo.
---

# Design base: identidade Egger e Mesquita (D-036)

Produto interno de um escritório de advocacia de massa: **profissional, sóbrio e denso de informação**, sem
ornamento. Toda decisão visual mora em `tokens.css` (nesta pasta, copiado para `static/css/tokens.css`) e nos
componentes de `templates/componentes/`. Os NOMES dos tokens são estáveis: mude valores, não nomes.

## Referências
- **Marca:** logos oficiais em `static/img/marca/` (origem: pasta "fotos" do usuário). Cores: roxo `#4F1F5C`
  (letras do logo), ouro `#F8B334` (o "e"), ameixa `#3E2745` (fundo da versão negativa). Letra do logo: Montserrat.
- **Escuro:** o painel de monitoramento da TI. Fundo azul-marinho quase preto, cartões um tom acima com borda fina,
  números grandes, status com ponto aceso em verde-água.
- **Estrutura de telas** vinda de terceiros (ex.: Power Apps): vale a organização, nunca a identidade.

## Temas
- `<html data-theme="light|dark">`. Um script inline no `<head>` aplica o tema salvo (`localStorage`, com try/catch)
  ou o `prefers-color-scheme`, antes da pintura. Botão de tema na topbar.
- **Escuro:** `--bg #060A12`, `--surface #0F1726`, `--surface-2 #141E31`, barra lateral `#0A101C`, bordas
  `#1D2940`. Primário = **ouro**, com texto escuro (`--on-accent`). Detalhe = roxo clareado (`--destaque`).
- **Claro:** `--bg #F5F4F7`, cartões brancos, bordas `#E6E2EA`. Primário = **roxo**, com texto branco. Detalhe =
  ouro escurecido (`--destaque`, AA).
- Texto sobre `--accent` usa SEMPRE `--on-accent`. Nunca `#fff` fixo: no escuro o botão é ouro e o texto é escuro.

## Tipografia e ícones
- **Montserrat** (OFL, vendorizada em `static/vendor/montserrat/<versao>/`, pesos 400/500/600/700): títulos (h1–h3),
  rótulos de seção em caixa alta espaçada (`--text-rotulo`, letter-spacing .16em), números de destaque
  (`--text-kpi`) e o número do processo.
- **Inter** (OFL, `static/vendor/inter/`): texto, tabelas, formulários.
- Números sempre `font-variant-numeric: tabular-nums`.
- **Ícones:** Lucide (ISC), sprite em `static/vendor/lucide/<versao>/`, traço 1.75, 20px na UI e 16px em tabela,
  via `componentes/icone.html`.
- **Formato brasileiro:** datas DD/MM/AAAA (HH:MM), dinheiro R$ 1.234,56. Nunca ISO na tela.

## Componentes
- **Shell:** barra lateral 248px (`--sidebar`, borda `--hairline`), logo oficial no topo com "Workflows" em rótulo,
  seções em rótulo Montserrat. Item ativo: `--fill-accent`, texto `--accent` e uma barra de 3px à esquerda. Topbar
  com título grande (Montserrat 600) e ações à direita. No celular, a barra lateral vira menu recolhível.
- **Cartão de resumo (KPI):** rótulo pequeno em `--text-2`, ponto de status aceso à direita (`--brilho-status`),
  número em `--text-kpi` Montserrat 600, complemento opcional em `--text-3` ("77 de 128"). Selecionado: borda `--accent`.
- **Card / painel:** `--surface`, borda `--hairline`, raio `--r-l`, `--shadow-1`. Título do painel em rótulo de seção.
- **Linhas rótulo → valor:** rótulo `--text-2` à esquerda, valor à direita (peso 500), separador `--hairline`.
- **Botões:** primário (`--accent` + `--on-accent`), secundário (`--surface` + borda `--borda-forte`), destrutivo
  (texto `--danger` sobre `--fill-danger`), altura 36px, raio `--r-m`.
- **Campos:** fundo `--surface-2`, borda `--hairline`, raio `--r-m`, foco `--ring`; label acima, erro abaixo em `--danger`.
- **Chips de status:** pill com fundo `--fill-success|warning|danger` e texto da cor; ponto quando indica estado vivo.
- **Item de lista selecionado:** `--fill-accent` + barra de 3px `--accent` à esquerda.
- **Estado vazio, toast, modal** (raio `--r-xl`), **bloco de código** (`--font-mono`, `--surface-2`).
- **Gráficos:** séries com as cores de status; eixos e grade em `--hairline`; legenda em `--text-2`.
- **Nó do canvas:** card com ícone em quadrado colorido por tipo, título, resumo de uma linha e badge de erro.

## Movimento
Transições de 150 a 200ms com `--ease`; nada chamativo. Respeite `prefers-reduced-motion`.

## Checklist da revisão visual (capturas light E dark, 1440 E 390)
Severidade **alta** (corrigir antes de fechar o módulo):
- [ ] Tela sem o shell, sem o logo oficial ou com cara de HTML padrão.
- [ ] Cor, raio, sombra ou tamanho fora dos tokens; `#fff` fixo sobre `--accent`; contraste abaixo de AA.
- [ ] Identidade de terceiros (roxo do Power Apps, azul iOS antigo etc.).
- [ ] Falta o estado vazio, de erro ou de carregando.
- [ ] Overflow horizontal ou sobreposição em 390px.
- [ ] Formulário sem label, sem erro por campo ou sem foco visível.
- [ ] Data em ISO ou dinheiro fora do formato brasileiro.
Severidade **média**:
- [ ] Título, KPI ou rótulo fora da Montserrat; números não tabulares.
- [ ] Espaçamento fora da escala de 4px; ícones de tamanhos misturados.
- [ ] Hierarquia fraca (o título não se destaca; a ação principal não é óbvia).
