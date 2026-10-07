---
name: design-base
description: Sistema visual base do Construtor de Workflows, limpo e simples no estilo Apple (light por padrão, dark disponível), com tokens, componentes, ícones e checklist de revisão visual. Carregue antes de criar ou alterar qualquer template, CSS ou tela, e na revisão visual de cada módulo.
---

# Design base: simples, limpo, estilo Apple

O objetivo é uma base **bonita, simples e neutra**, que sirva para qualquer projeto. Um designer
vai fazer o acabamento depois. Por isso, **organização vale mais que ornamento**: toda decisão
visual mora em `tokens.css` e nos componentes, para que o designer mude o visual inteiro mexendo
só nesses dois lugares.

## Princípios (referência: apps nativos da Apple, como Ajustes, Lembretes e Notas)
- Hierarquia por **tipografia e espaço**, não por bordas e caixas.
- Muito respiro: escala de 4px, conteúdo com largura máxima confortável.
- **Um** acento de cor (azul do sistema). As demais cores só têm significado (sucesso, erro, aviso).
- Superfícies brancas sobre fundo cinza bem claro, cantos arredondados, sombras quase invisíveis.
- Nada decorativo: sem gradientes, texturas ou ilustrações. Ícones finos e consistentes.
- **Light é o padrão; dark é alternável e segue o sistema.**

## Base pronta
- Copie `tokens.css` (nesta pasta) para `static/css/tokens.css` e use SÓ esses tokens. Nenhuma
  cor, raio, sombra ou tamanho escrito à mão em outro arquivo.
- **Fonte:** Inter vendorizada (OFL) em `static/vendor/inter/`. SF Pro não pode ser usada fora de
  plataformas Apple (licença).
- **Ícones:** Lucide (ISC) vendorizado como sprite SVG em `static/vendor/lucide/<versao>/`, traço
  1.75, 20px na UI e 16px em tabela. Não use SF Symbols (licença restrita a Apple). Use o include
  `componentes/icone.html` com `nome="..."`.
- **Tema:** `<html data-theme="light|dark">`. Um script inline no `<head>` aplica o tema salvo
  (`localStorage`, com try/catch) ou o `prefers-color-scheme`, antes da pintura. Botão de tema na
  topbar.
- **Vidro (opcional, DESLIGADO):** existe a classe `.vidro` nos tokens, mas não use agora. Fica
  para o designer decidir na etapa de acabamento.

## Componentes (todos em `templates/componentes/`)
- **Shell:** sidebar 240px (`--surface`, separador `--hairline`), item ativo com `--fill-accent`
  e texto `--accent`; topbar com título grande da página à esquerda e ações à direita. No mobile,
  a sidebar vira um menu recolhível.
- **Card / grupo:** `--surface`, raio `--r-l`, `--shadow-1`. Listas de configuração no estilo
  "grupo inset" do iOS: linhas separadas por `--hairline`, rótulo à esquerda e valor à direita.
- **Botões:** primário (`--accent` sólido), secundário (`--fill` com texto `--accent`), destrutivo
  (texto `--danger`), altura 36px, raio `--r-m`, ícone opcional.
- **Campos:** fundo `--fill`, sem borda, raio `--r-m`, foco com `--ring`; label acima, erro abaixo
  em `--danger`.
- **Controle segmentado** para filtros curtos. **Toggle** no estilo iOS para booleanos.
- **Tabela:** dentro de card, sem linhas verticais, cabeçalho em `--text-2` e `--text-sm`, hover
  em `--fill`, ações à direita como botões de ícone.
- **Badge de status:** pill tintada com um ponto: rascunho (cinza), ativo (verde),
  executando (azul), sucesso (verde), erro (vermelho).
- **Estado vazio:** ícone em círculo `--fill`, título, uma frase e o botão primário.
- **Toast**, **modal** (raio `--r-xl`, fundo escurecido) e **bloco de código/JSON**
  (`--font-mono`, fundo `--fill`, botão copiar).
- **Nó do canvas:** card com ícone em quadrado arredondado colorido por tipo (gatilho = laranja,
  HTTP = azul, saída = verde), título, resumo de uma linha e badge de erro.

## Movimento
Transições de 150 a 200ms com `--ease`; nada chamativo. Respeite `prefers-reduced-motion`.

## Checklist da revisão visual (abra as capturas de light E dark)
Severidade **alta** (corrigir antes de fechar o módulo):
- [ ] Tela sem o shell ou com cara de HTML padrão do navegador.
- [ ] Cor, raio, sombra ou tamanho fora dos tokens; texto ilegível no dark.
- [ ] Falta o estado vazio, de erro ou de carregando.
- [ ] Overflow horizontal ou sobreposição em 390px.
- [ ] Formulário sem label, sem erro por campo ou sem foco visível.
- [ ] Markup repetido em vez de componente.
Severidade **média** (corrigir se sobrar orçamento):
- [ ] Espaçamento fora da escala de 4px; ícones de tamanhos misturados.
- [ ] Hierarquia fraca (o título não se destaca; a ação principal não é óbvia).
