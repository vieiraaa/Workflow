---
name: frontend
description: Regras de templates Django, static, JS do canvas (Drawflow, sem build) e testes de tela do Construtor de Workflows. Carregue antes de mexer em templates/ ou static/. Sempre use junto com a skill design-base.
---

# Frontend (Django templates, sem build)

Carregue também a skill `design-base`: ela define a aparência. Esta skill define a mecânica.

## Estrutura
- `templates/base.html` (shell: sidebar, topbar, área de conteúdo, toasts, troca de tema).
- `templates/componentes/` (includes: `card.html`, `tabela.html`, `vazio.html`, `campo.html`,
  `botao.html`, `badge_status.html`, `paginacao.html`, `modal.html`).
- `templates/<app>/<view>.html` estendem `base.html` e usam os componentes. Não repita markup:
  se apareceu duas vezes, vira componente.
- `static/css/tokens.css`, `static/css/app.css`, `static/js/app.js` (tema, toasts, modal),
  `static/js/canvas/` (editor), `static/vendor/<lib>/<versao>/`.

## Regras
- Sem CDN: tudo vendorizado com licença e versão registradas em DECISOES.md.
- Escape sempre: sem `|safe`/`mark_safe` em dado do usuário; no JS, `textContent`, nunca
  `innerHTML` com dado do usuário.
- Forms de mutação: POST + `{% csrf_token %}`; `fetch` envia `X-CSRFToken`.
- JS fino: o JS só converte entre o formato do Drawflow e o grafo canônico (`docs/spec/grafo.yaml`)
  e cuida da UX. Toda validação acontece no servidor, e os erros voltam para o nó certo no canvas.
- Esconder botão é UX; a segurança está no servidor.

## Editor de canvas (M2)
- Paleta lateral com os 3 tipos de nó (ícone + nome), arrastar para o canvas.
- Nó = card com ícone, título, resumo (ex.: `GET api.exemplo.com/...`) e badge de erro.
- Clicar no nó abre um painel lateral (inspector) com o formulário da configuração.
- Toolbar flutuante: salvar, executar, zoom +/-/ajustar, status (rascunho/ativo).
- Atalhos: Delete remove o nó, Ctrl+S salva. Aviso de alterações não salvas ao sair.

## Testes
- Toda tela: teste de render com `assertTemplateUsed` do template específico.
- Canvas: smoke em Playwright (criar 3 nós, conectar, salvar, recarregar, grafo igual).
- Toda tela listada em `docs/spec/telas.yaml` (é a fonte do `scripts/telas.py`).
