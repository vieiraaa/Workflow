# Painel de Processos: guia de implementação da nova identidade

Referência visual aprovada: `painel-v2.html` (nesta pasta). Abra no navegador; é autocontido e interativo.
A versão anterior (`painel.html`, `painel-claro.png`, `painel-escuro.png`) fica só como histórico.

Este guia é para quem for levar a prévia para o app real (Workflows, módulo Jurídico → Cadastro de processos).
A prévia usa dados fictícios. O comportamento descrito aqui deve ser ligado aos dados reais.

## 1. Tokens de cor

Defina como variáveis CSS (ou no tema do framework do app). O tema claro fica em `:root`; o escuro redefine os mesmos nomes.

| Token | Claro | Escuro | Uso |
|---|---|---|---|
| `--fundo` | `#F6F4F8` | `#17101C` | fundo da área principal |
| `--superficie` | `#FFFFFF` | `#211827` | painéis |
| `--superficie-2` | `#F1EDF4` | `#2A1F31` | campos, hover, trilhos de barra |
| `--borda` | `#E6E0EB` | `#35283D` | divisórias |
| `--borda-forte` | `#D2CAD9` | `#4A3A54` | contorno de botões e blocos |
| `--texto` | `#1F1625` | `#F2EBF4` | texto principal |
| `--texto-2` | `#5D5367` | `#C0B2C8` | rótulos |
| `--texto-3` | `#85798F` | `#918299` | metadados |
| `--primaria` | `#4F1F5C` | `#F8B334` | botão principal, seleção |
| `--primaria-texto` | `#FFFFFF` | `#2B1B05` | texto sobre a primária |
| `--primaria-suave` | `rgba(79,31,92,.07)` | `rgba(248,179,52,.12)` | linha/cliente selecionado |
| `--rotulo` | `#7A3F8C` | `#CFA8DC` | títulos de grupo da ficha, código do tribunal |
| `--ouro` | `#F8B334` | `#F8B334` | emblema, item ativo da lateral, foco, folha da audiência |
| `--ouro-texto` | `#8A5B00` | `#F8B334` | texto dourado legível sobre fundo claro |
| `--lat-fundo` | `#3E2745` | `#0F0912` | barra lateral (ameixa da marca) |
| `--lat-texto` | `#EDE3F1` | `#EDE3F1` | texto da lateral |
| `--lat-texto-2` | `#B7A2C1` | `#9E8AA8` | itens inativos da lateral |
| `--ok` | `#12805F` | `#4FD1A5` | status Cadastrado |
| `--conf` | `#2F5FC4` | `#93B5FF` | status Conferir |
| `--pend` | `#C2412D` | `#FF8B7B` | status Com pendências, campo faltando |
| `--erro` | `#C42B3C` | `#FF6B78` | erro de leitura de PDF |

Cada cor semântica tem uma versão `-suave` (a mesma cor com ~10% de opacidade) para o fundo dos chips.

Regras:
- **Dourado é da marca e das ações**, nunca de status. Na versão anterior "Conferir" era dourado e se confundia com o botão principal.
- **A lateral é sempre ameixa**, nos dois temas. É o lugar de maior presença da marca.
- O tema escuro é **ameixa profundo**, derivado da versão negativa do logo, e não azul quase preto.

## 2. Tipografia

| Papel | Fonte | Onde |
|---|---|---|
| Marca | Montserrat 600 | título da página, títulos de painel e de grupo, nome na lateral |
| Texto | IBM Plex Sans 400/500/600 | todo o resto da interface (substitui a Inter) |
| Números | IBM Plex Mono 400/600 | número CNJ, contagens, dia da audiência |

Google Fonts:
`https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap`

- Rótulos em caixa normal (sem CAIXA ALTA espaçada).
- `font-variant-numeric: tabular-nums` em tudo que tem números alinhados.
- Base 14px; título da página 26px; número CNJ da ficha 21px.

## 3. Estrutura da tela

1. **Barra lateral (236px):** emblema dourado + "Workflows / Egger e Mesquita"; itens com ícone de linha; item ativo com fundo dourado suave e texto dourado, sem barrinha lateral. Rodapé com usuário e botão de tema.
2. **Topo:** "Painel de Processos", hora da última atualização, ações *Audiências (n)*, *Menu*, *+ Enviar PDFs*.
3. **Fluxo do cadastro** (substitui os 6 cards de KPI):
   - **Entrada de PDFs:** quantos estão em leitura (ponto dourado pulsando) e quantos deram erro de leitura (link para o log).
   - **Barra em escala:** um segmento por etapa, com largura proporcional à contagem. A ordem é a do fluxo: Com pendências → Conferir → Cadastrado.
   - **Etapas clicáveis:** número, nome e legenda curta. Clicar filtra a lista; clicar de novo limpa o filtro.
4. **Três colunas:** Clientes | Processos | Ficha. Abaixo de 1240px os clientes viram uma grade acima; abaixo de 900px tudo fica em uma coluna e a lateral vira barra no topo.

## 4. Componentes da ficha

- **Número CNJ decomposto:** `NNNNNNN-DD.AAAA.J.TR.OOOO`, cada parte com legenda (sequencial, dígito, ano, justiça, sigla do tribunal, origem). O código do tribunal usa `--rotulo`.
  Mapa usado na prévia: `8.13` TJMG, `8.16` TJPR, `8.19` TJRJ, `8.21` TJRS, `8.24` TJSC, `8.26` TJSP. Completar com os demais tribunais.
- **7 campos obrigatórios:** 7 marcadores (preenchido = encontrado, contorno = faltando) + "N de 7 campos obrigatórios".
  Campos: Número, Tribunal, Comarca, Juízo, Adverso, Valor da causa, Distribuído em.
  Campo faltando aparece como "não encontrado no PDF", sublinhado tracejado em `--pend`.
- **Ação principal muda com o status:**
  - Conferir → "✓ Marcar cadastrado no Espaider" + Editar
  - Com pendências → "Completar campos" + Abrir PDF
  - Cadastrado → "✓ Cadastrado no Espaider em dd/mm/aaaa" + Editar
- **Audiência:** folha de calendário (mês no topo dourado, dia em mono), tipo, hora, comarca e juízo, com o aviso "Agenda manual: crie a agenda da audiência no Espaider".
- **Confere com o CNJ:** faixa verde com tribunal, distribuição e comarca marcados.

## 5. Ligação com os dados reais

Hoje a fonte é a planilha `PLANILHA_PROCESSOS_ESPIDER.xlsx` (abas PROCESSOS, LOG DE ERRO, STATUS, N8N EXEC).

| Na tela | Origem |
|---|---|
| Com pendências / Conferir | coluna de status da aba PROCESSOS (`COM PENDÊNCIAS` / `CONFERIR`) |
| Cadastrado | coluna "Cadastrado no Espaider" = Sim |
| Marcadores dos 7 obrigatórios | quais dos 7 campos estão vazios na linha |
| Em leitura | aba STATUS = "Rodando" |
| Erro de leitura / ver log | aba LOG DE ERRO |
| Clientes: cadastrados/total | agrupar PROCESSOS por cliente |
| Audiências (n) | processos com audiência agendada |
| "Marcar cadastrado no Espaider" | gravar "Cadastrado no Espaider" = Sim, com data e usuário |

Importante: um processo passa de *Com pendências* para *Conferir* quando os 7 campos ficam preenchidos. A contagem total da barra é a soma das três etapas.

## 6. Acessibilidade e detalhes

- Foco de teclado visível (contorno dourado de 2px).
- Respeitar `prefers-reduced-motion` (o ponto pulsando para).
- Etapas, clientes e processos são `<button>`; o filtro ativo usa `aria-pressed`, e a linha selecionada usa `aria-current`.
- Estado vazio da lista: "Nenhum processo com esses filtros. Limpe a busca ou escolha outro cliente."
