# Construtor de Workflows

Aplicação Django com três papéis (Adm, Coordenador, Usuário base) e um construtor visual de
workflows estilo n8n: Gatilho manual → Requisição HTTP → Saída. Piloto feito por um time de
agentes no Maestri (Lead "Orquestrador", Back "Forja", Front "Vitral", QA "Lupa").

## Fontes da verdade (leia só o trecho que a tarefa cita, pelo id)
- `docs/spec/papeis.yaml` (PAP-xx), `permissoes.yaml` (PRM-xx), `grafo.yaml` (FLX/GRF/PLH-xx),
  `estados.yaml` (EST/EXE-xx), `seguranca.yaml` (SEG-xx), `telas.yaml` (TEL-xx), `usuarios.yaml` (USR-xx).
- `DECISOES.md`: decisões de uma linha. `PROGRESSO.md`: onde o time está.
- `tasks/T-0xx.yaml`: objetivo, aceite, `arquivos:` (fronteira dura), dono, depende_de.
- Skills em `.claude/skills/`: `backend`, `integracao`, `frontend`, `design-base`.
  Carregue a da área ANTES de escrever código nela.

## Stack
- Python 3.14 (venv em `.venv/`), Django 5.2 LTS, Postgres. httpx síncrono. Playwright (Python).
- Banco da aplicação: Supabase via `DATABASE_URL` (session pooler, SSL). Lida só em runtime.
- Testes: Postgres LOCAL (Postgres.app, `localhost:5432`, usuário do SO, sem senha), banco
  `construtor_teste`. `config/travas.py` aborta se a URL de teste apontar para supabase.
- Frontend sem build: templates Django + CSS/JS em `static/`, libs vendorizadas
  (`static/vendor/<lib>/<versao>/`), Drawflow no canvas, Inter e Lucide.
- Portável para Windows: `pathlib`, `sys.executable`, `subprocess` com lista de argumentos.

## Layout
```
config/            settings/{base,dev,teste}.py, urls.py, travas.py
apps/nucleo/       mixins, utilidades comuns
apps/contas/       Usuario (custom), papéis via Groups, permissoes.py (motor único)
apps/fluxos/       Fluxo, grafo canônico, editor (M2)
apps/execucoes/    Execucao, ExecucaoNo, histórico (M3)
apps/motor/        executor, cliente HTTP, SSRF, placeholders, mascaramento (M3)
templates/         base.html, componentes/, <app>/<view>.html
static/            css/tokens.css, css/app.css, js/app.js, js/canvas/, vendor/
scripts/           check.py, telas.py
tests/             unit/<app>/, unit/frontend/, acceptance/, adversarial/, e2e/, conftest.py
docs/              spec/, telas/mN/, prs/, ENTREGA.md
```

## Comandos
```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py runserver                  # usa config.settings.dev
.venv/bin/python scripts/check.py --rapido            # durante o trabalho (arquivos tocados)
.venv/bin/python scripts/check.py                     # completo, fim de módulo
.venv/bin/python scripts/telas.py --modulo 1          # capturas em docs/telas/m1/
.venv/bin/python manage.py semear_demo                # dados fictícios + 3 usuários de demo
.venv/bin/python scripts/demo.py --porta 8001      # demo local (banco construtor_demo, nunca Supabase); recarrega sozinho
# :8000 = app com Supabase rodando a cópia estável ../construtor-workflows-estavel (D-018); nunca rode o time lá
```

## Convenções
- Papéis = Groups com nomes exatos `Adm`, `Coordenador`, `Base` (PAP-01).
- Login por e-mail (`Usuario.USERNAME_FIELD = "email"`).
- Permissão SÓ pelo motor: `pode(usuario, acao, objeto=None)`, `escopo(usuario, qs)`,
  `PermissaoMixin`. Nunca `user.groups` em view ou template; o template recebe flags prontas.
- Views class-based; cada view tem template `<app>/<view>.html` e docstring com o CONTEXTO
  (contrato Back↔Front). Mutação só por POST + CSRF → redirect + `messages`.
- Listagens: paginação 25, `?q=` busca, `?ordem=` ordenação, queries constantes.
- Nomes de rota fixos (spec `telas.yaml`): `login`, `logout`, `inicio`, `contas:usuarios`,
  `contas:usuario_novo`, `contas:usuario_editar`, `contas:trocar_senha`, `fluxos:lista`,
  `fluxos:editor`, `fluxos:salvar_grafo`, `fluxos:executar`, `execucoes:lista`, `execucoes:detalhe`.
- 403/404 usam templates do produto (`erros/403.html`, `erros/404.html`, com shell). TEL-10/11.
- Testes: pytest + pytest-django. Marcador `@pytest.mark.modulo("mN")`. Fixtures de papel em
  `tests/conftest.py`: `usuario_adm`, `usuario_coordenador`, `usuario_base`, e clientes logados
  `cliente_adm`, `cliente_coordenador`, `cliente_base`, `cliente_anonimo`.
- Código em português (nomes de domínio), mensagens ao usuário em português claro.

## Fronteiras de arquivo (quem edita o quê)
- Forja (Back): `apps/`, `config/`, `scripts/`, `requirements*`, `pyproject.toml`, `manage.py`,
  `tests/unit/` (menos `frontend/`), `tests/conftest.py`.
- Vitral (Front): `templates/`, `static/`, `tests/unit/frontend/`, `tests/e2e/`.
- Lupa (QA): `tests/acceptance/`, `tests/adversarial/`. Não lê código da aplicação.
- Orquestrador (Lead): `docs/`, `tasks/`, `CLAUDE.md`, `DECISOES.md`, `PROGRESSO.md`, `.gitignore`.
- Git & Gitea: merges na main, tags e push para o Gitea — SÓ a pedido do usuário; permissões próprias
  (maestri/git-gitea.settings.json). Os demais agentes continuam sem push/merge.
Fora da sua fronteira: peça ao dono. Não edite arquivo que outro agente está mexendo.

## Git
- Todos na mesma branch, no mesmo diretório. Só o Lead troca de branch.
- `git add <caminhos seus>` — NUNCA `git add -A` nem `git add .`.
- Um commit por tarefa, com trailers:
  `Task: T-0xx` / `Agent: <lead|back|front|qa|seguranca>` / `Model: <modelo>`.
- NUNCA push, merge na main, rebase ou reset --hard.

## Qualidade e limites
- Tela pronta = skill `design-base` + estados vazio/carregando/erro/sucesso + revisão visual.
- Loop: escreve → `check --rapido` → corrige. Máx. 3 ciclos vermelhos; depois `needs-human`.
- Proibido apagar, pular ou enfraquecer teste. Teste de aceite errado → reporte ao Lead.
- Segredos: nunca leia `.env`; nada de segredo em código, log ou saída. Só dados fictícios.
- Testes nunca tocam a internet nem a `DATABASE_URL`.

## Linha de resultado (todos)
`T-0xx | verde/vermelho/needs-human | ciclos: N | suposições: [...] | editou aceite: sim/não | commit: <hash>`
enviada com `maestri ask "Orquestrador" "<linha>"`.
