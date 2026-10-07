# Decisões (uma linha cada; ADR só para o que cruza módulos)

- D-001 · Fase 0 · Python 3.14 local (é o que existe na máquina); Django 5.2 LTS (>=5.2.8, suporta 3.14). Toda dependência nova: confirmar wheel macOS+Windows para 3.14.
- D-002 · Fase 0 · Testes em Postgres local (Postgres.app 18, localhost:5432, usuário do SO), banco `construtor_teste`; Supabase só para a aplicação.
- D-003 · Fase 0 · Usuário custom `contas.Usuario` desde o início (AbstractUser, login por e-mail único, campo `nome`).
- D-004 · Fase 0 · Papéis = Groups `Adm`, `Coordenador`, `Base`; cada usuário tem exatamente um papel (PAP-02).
- D-005 · Fase 0 · Matriz de permissões em `docs/spec/permissoes.yaml`; o motor `apps/contas/permissoes.py` lê a spec (não duplica regra).
- D-006 · Fase 0 · Time no Maestri: recrutas rodam `claude --model sonnet --append-system-prompt-file maestri/papeis/<papel>.md` na raiz (o `--role` do Maestri forçava o cwd em `.maestri/roles/`, sem `.claude/`).
- D-007 · Fase 0 · QA roda em Claude Sonnet (escolha do usuário).
- D-008 · Fase 0 · Inter 5.3.0 (@fontsource-variable/inter), OFL-1.1, subsets latin e latin-ext, em static/vendor/inter/5.3.0/.
- D-009 · Fase 0 · Lucide 1.52.0 (lucide-static), ISC, sprite SVG em static/vendor/lucide/1.52.0/.
- D-010 · Fase 0 · Spec em YAML válido: todo `texto:` em bloco `>` (o motor e o telas.py fazem yaml.safe_load).
- D-011 · M1 · Senha exige 5+ caracteres distintos (SenhaRepetitivaValidator, Forja), além dos validadores do Django; vinha de um teste de aceite além da spec → incorporado em USR-04.
- D-012 · M1 · Rate limit/bloqueio de login fora do escopo do piloto (lacuna do T-008); registrar como pendente na ENTREGA.
- D-013 · M2 · Lupa autorizada pelo usuário a criar portais de visualização (iOS/Android/Windows). Sem simulador/emulador na máquina → portais de navegador com viewport 390x844, 412x915, 1440x900 contra servidor demo local (config/settings/demo.py, nunca Supabase).
- D-014 · M2 · Menu móvel 'não abre' nos portais: artefato do portal (visibilityState=hidden pausa transições CSS no WebKit), não bug da app; Playwright WebKit instalado para testar o motor do iOS/Safari.
- D-015 · M2 · Drawflow 0.0.60 (npm drawflow), MIT, vendorizado em static/vendor/drawflow/0.0.60/.
- D-016 · M3 · Usuário ligou a Lupa a um terminal 'OpenCode - Test Terminal' no canvas (confirmado); mantido. Revisor de Segurança = Atalaia (opus), entra na T-030 e sai depois.
