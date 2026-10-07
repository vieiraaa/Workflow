---
name: backend
description: Regras de backend Django do Construtor de Workflows (models, migrations, forms, views, urls, motor de permissão, listagens). Carregue antes de escrever ou alterar código em apps/ que não seja apps/motor.
---

# Backend Django

## Estrutura
- `apps/contas/` (usuários, papéis, motor de permissão em `permissoes.py`), `apps/fluxos/`,
  `apps/execucoes/`, `apps/nucleo/` (mixins e utilidades comuns).
- Testes de unidade em `tests/unit/<app>/`.

## Regras
- **Permissão só pelo motor:** `pode(usuario, acao, objeto=None)`, escopo de queryset
  (`escopo(usuario, Model.objects)`) e o mixin `PermissaoMixin`. Nunca `if user.groups...` em view.
  A matriz vem de `docs/spec/permissoes.yaml`; o motor lê a spec e não duplica a regra.
- **Views:** class-based. Cada view tem template específico (`<app>/<view>.html`) que estende
  `base.html`. O contexto é documentado na docstring da view (é o contrato com o template).
- **Listagens:** escopo no banco, `select_related`/`prefetch_related`, paginação de 25, busca e
  ordenação por querystring, número de queries constante (teste com `django_assert_num_queries`).
- **Mutação:** só POST com CSRF. Depois de POST: redirect + `messages` (o template exibe como toast).
- **Formulários:** validação no form/model (`clean`), mensagens em português claro, erros por
  campo. O template renderiza erros; a view nunca monta HTML.
- **Respostas JSON** (canvas): `JsonResponse` com `{"ok": bool, "erros": [{"campo", "mensagem"}]}`.
- **Admin:** registre todos os models com `list_display`, `search_fields` e `list_filter`.
- **Migrations:** uma por mudança de model; nomes descritivos (`--name`).

## Antes de dar a tarefa por pronta
- Rota testada com Adm, Coordenador, Usuário base e anônimo.
- Lista vazia, lista com 30 itens (paginação) e objeto de outro usuário (IDOR) testados.
