# Identidade visual Egger e Mesquita — branch `feat/identidade-eem`

Pedido do usuário (20/10/2026): visual mais profissional, com a identidade do escritório. Modo escuro em azul-marinho
quase preto, inspirado no painel de monitoramento da TI, e modo claro na mesma base. A prévia foi aprovada antes da
implementação. Decisões: D-036 (identidade) e D-037 (Montserrat vendorizada). A branch parte de `feat/m8-cadastro`.

## O que entra
- **design-base reescrita** (`.claude/skills/design-base/`):
  - Cores da marca: roxo #4F1F5C, ouro #F8B334 e ameixa #3E2745.
  - Escuro: fundo #060A12 e primário ouro. Claro: fundo #F5F4F7 e primário roxo.
  - O texto sobre o primário usa `--on-accent`.
  - Contraste AA conferido em todos os pares.
  - Os **nomes dos tokens foram mantidos**: só os valores mudaram.
- **Todas as telas** (M0–M8, editor/canvas, Funções, Jurídico, login, 403/404):
  - Logo oficial e favicon com o emblema E·e·M.
  - Montserrat em títulos, rótulos de seção e números de destaque; Inter no texto.
  - Cartões de resumo com ponto de status aceso.
  - Nós do canvas com as cores da marca.
  - Menu agrupado: Jurídico e Administração.
- **Papel do Vitral reescrito** (`maestri/papeis/front.md`) e carregado no Maestri, com a identidade definitiva,
  formato brasileiro, AA e revisão das próprias capturas.
- Nenhuma regra de negócio, rota, contexto ou mensagem mudou.

## Testes e revisão
- Revisão visual de todos os módulos: nenhum item de gravidade alta. Os médios foram corrigidos:
  - grupo Administração no menu (T-087);
  - título longo no celular e rótulo de KPI (T-088).
- Instabilidade no webkit corrigida na causa (T-089): laço do ResizeObserver no detalhe da execução, agora adiado com
  `requestAnimationFrame`. Prova: 10 de 10 execuções seguidas, sem mudar o teste.
- 336 capturas regeneradas (`docs/telas/m0` … `m8`, light/dark × 1440/390).
- Check completo (20/10): **VERDE**.

## Pendente do usuário
Versão **negativa do logo em PNG transparente**, com o "e" dourado. Até ela chegar, o modo escuro usa o logo oficial
com filtro branco.
