# M7a · Núcleo das Funções — branch `feat/modulo-7a`

Pedido do usuário (13/10/2026): adiantar o núcleo da tela **Funções** antes do M6; o **Adm faz o papel de TI** (D-029).
Spec: `docs/spec/funcoes.yaml` (FUN-01..13, FUN-07a). Decisões: D-029, D-030, D-031.

## O que entra
- **Menu "Funções"** (logo após Início) e **catálogo em cartões** (TEL-23): ícone, nome, descrição, a SUA última
  execução com link para o resultado, botão Executar; busca; Adm vê rascunhos/inativas e gerencia pelo menu do cartão.
- **Cadastro (só Adm, TEL-24)**: fluxo, nome, descrição, ícone, **entradas** (texto, número, data com padrão
  "hoje"/"ontem", booleano, lista) e **liberação** para todos, setores escolhidos ou papéis escolhidos.
- **Publicação com versão congelada** (FUN-04): publicar copia o grafo; editar o fluxo depois não muda a função até
  "Publicar nova versão". Fluxo com pendência não publica. Ativar/desativar; sem exclusão.
- **Executar para mim** (TEL-25, FUN-06/07): formulário curto validado no servidor; execução síncrona com o grafo
  publicado e todas as proteções do motor v2; `$parametros.<nome>` nas expressões e no Código, sempre como DADO.
- **Resultado** (TEL-26, FUN-09): parâmetros usados e a saída do último nó em tabela (20 colunas × 200 linhas);
  sem canvas, requisições, logs nem credenciais para quem não é Adm (Adm tem "Detalhe técnico").
- **Privacidade** (D-031, FUN-10): execução de função é vista só pelo executor e pelo Adm, em lista, detalhe e Home.
- Credenciais pelo setor do fluxo (FUN-11); uma execução por usuário e função por vez (FUN-12).

## Fora (depois do M6, D-030)
"Atualizar para todos" e resultado oficial (D-d em aberto), nós de efeito geral, agendamento/próxima execução,
atividades em massa (CSV), exportar CSV.

## Testes
- Aceite m7a (Lupa, só pela spec) e adversarial m7a (108 ataques: IDOR/escopo, privacidade para_mim, injeção por
  parâmetro, versão congelada, CSRF, mass assignment, XSS em chromium e webkit, credencial): **201 verdes**.
- Achados do adversarial: 1 defeito real (booleano inválido → 500) corrigido em T-072; surrogate em formulário
  esclarecido na spec (o Django já o troca por U+FFFD) — FUN-07a.
- Defeitos de teste apontados pelos construtores e conferidos pelo Lead (4), corrigidos pela própria QA.
- Check completo (13/10): **VERDE** — ruff, format, makemigrations, SEG-08, pytest + cobertura, pip-audit, telas.

## Revisão visual
48 capturas em `docs/telas/m7a/` (light/dark × 1440/390, Adm e Base): 0 altas. Média: data dos parâmetros no
resultado em formato ISO (2026-10-12) em vez de 12/10/2026.

## Para revisar no PR
`apps/funcoes/` (models, entradas, views, apresentacao), `apps/contas/permissoes.py` (escopo `liberadas`),
`apps/motor/` ($parametros), migrations `funcoes 0001` e `execucoes 0004`, `templates/funcoes/`.

## Implantação (após o merge)
Migrations no Supabase (`funcoes 0001`, `execucoes 0004`, junto com as do M5) — só com OK do usuário.

## Demo
Função **"Chamados do dia"** publicada no demo (entrada "Dia", padrão ontem) sobre o fluxo Digisac do usuário;
execução #699 (dia 12/10) com sucesso, 4 chamados.
