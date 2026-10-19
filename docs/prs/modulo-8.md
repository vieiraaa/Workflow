# M8 · Jurídico · Cadastro de processos — branch `feat/m8-cadastro`

Pedido do usuário (19/10/2026): trocar o fluxo n8n "ATIVOS-DADOS", o Excel e o Power Apps por um módulo do próprio
sistema. O LLM continua sendo o **mesmo app do Dify**; os PDFs entram pelo nosso site; os dados ficam no nosso banco; o
número é validado no CNJ (DataJud); o painel segue a estrutura do Power Apps com a **nossa** identidade visual.
Spec: `docs/spec/juridico-cadastro.yaml` (CAD-01..23, CAD-07a; TEL-27..35). Decisões: D-033, D-034, D-035.
A branch parte de `feat/no-chamar-n8n`, que entra junto se ainda não estiver na main.

## O que entra
- **Menu Jurídico › Cadastro de processos** para o Adm e para os setores liberados na Configuração (CAD-01/02).
- **Enviar PDFs** (até 10 por vez, 30 MB cada, só PDF de verdade) e **Cadastrar pelo CNJ** (até 50 números + carteira).
  Um worker processa a fila, um item por vez, como o n8n (CAD-03/05/07).
- **Leitura pelo Dify**: chamadas iguais às do n8n (texto em `chat-messages`; PDF escaneado vai por `files/upload`).
  Melhoria: processos longos mandam o começo **e o fim** (25k + 15k caracteres), em vez de cortar em 40k (CAD-07).
- **Validação no CNJ**: dígito verificador e DataJud. Confere tribunal, data de distribuição e comarca; o que
  diverge vira pendência; o CNJ só preenche campo vazio. Ordem de prioridade: PDF > manual > CNJ (CAD-10/11).
- **Duplicidade**, como o usuário pediu (CAD-06):
  - Mesmo arquivo: "Já temos este arquivo: processo X · enviado por Nome (e-mail) em data", sem chamar o Dify.
  - Mesmo número: atualiza e avisa "Este processo já existia: cadastrado por Nome (e-mail) em data via PDF/CNJ/manual".
  - Número com dígito inválido nunca se mistura com outro processo.
- **Painel** (estrutura do Power Apps): Clientes | Processos | Detalhes, contadores clicáveis, Menu e Audiências.
  Também: **conferência** com a origem de cada campo e "Marcar como cadastrado no Espaider"; **Envios**; **Log de
  erros e desempenho** com gráfico por dia e erros por etapa; **Audiências**; **Cadastro manual**; **Excluir/
  restaurar**; **Configuração** (Adm), com carteiras, setores, credenciais e "Testar conexão".
- **Segurança** (CAD-18/07a):
  - Chaves só no cofre de credenciais, mascaradas também quando o Dify ou o DataJud as devolvem nos dados.
  - PDFs no disco do servidor (`arquivos_privados/`, fora do git), baixados só com login.
  - CPF/CNPJ mascarado na lista.
  - TLS nunca desligado. O sistema confia no repositório de certificados do sistema operacional e numa CA opcional
    só para o host do Dify, que hoje usa o certificado do FortiGate.

## Fora (CAD-22)
Assistente IA, Robô Espaider, OneDrive/e-mail, API do Espaider, importar a planilha atual e o Agente de Prazos.

## Testes
- Aceite (Lupa, escrito só a partir da spec, com Dify e DataJud falsos e PDFs fictícios): verde.
- Adversarial (Lupa): IDOR, upload hostil, Dify/DataJud hostis, configuração hostil, corridas de duplicidade, CSRF
  e XSS em chromium e webkit. Achou **8 defeitos reais**, todos corrigidos em T-083:
  - 500 em corrida de cadastro manual;
  - erro em PDFs paralelos do mesmo número;
  - dígitos Unicode furando a unicidade;
  - PEM aceitando chave privada;
  - processo perdido com DataJud estranho;
  - chave refletida nos campos;
  - URL ftp/RTL na Configuração;
  - carteira inativa.
- Revisão visual: 96 capturas em `docs/telas/m8/` (light/dark × 1440/390, Adm e Base). Nenhum problema de
  gravidade alta; os 2 médios foram corrigidos (valor `12.500,00` em T-081; credenciais em lista de escolha em T-082).
- Check completo (19/10, após T-085): **VERDE**. Inclui ruff, format, makemigrations, SEG-08, pytest com cobertura, pip-audit e telas.
- Dois testes adversariais transacionais sem `serialized_rollback` derrubavam os e2e seguintes no check completo
  (155 erros de setup). Corrigidos pela QA em T-084 e T-085.

## Para revisar no PR
`apps/juridico/` (models, processamento, mescla, cnj, clientes Dify/DataJud, views, worker), `apps/motor/http.py`
(corpo binário, `contexto_tls`), `apps/contas/permissoes.py` (`cadastro.*`), migrações `juridico 0001/0002`,
`templates/juridico/`, `scripts/demo.py` (worker e chave de demo), `requirements.txt` (pypdf, truststore).

## Implantação
1. OK do usuário para aplicar as migrações no Supabase (M5, M7a e M8 juntas).
2. Subir o worker junto com o servidor: `python manage.py processar_cadastros`.
3. Em Credenciais (sem setor): "Dify" (Bearer, chave `app-…`) e "DataJud" (Header `Authorization`, valor
   `APIKey …`). Depois, em Cadastro › Configuração, escolher as duas, marcar os setores e clicar em "Testar conexão".

## Roteiro de teste no notebook da empresa (Windows, rede oficial)
1. `git pull` e `git checkout feat/m8-cadastro`. Depois `py -3.14 -m venv .venv` e
   `.venv\Scripts\pip install -r requirements.txt`.
2. No `.env` do notebook (só você digita): `DATABASE_URL`, `CREDENCIAIS_CHAVE`, `SECRET_KEY`.
   Se for usar o Supabase, só depois do OK das migrações; então rode `.venv\Scripts\python manage.py migrate`.
3. Terminal 1: `.venv\Scripts\python manage.py runserver`. Terminal 2: `.venv\Scripts\python manage.py processar_cadastros`.
4. Entre como Adm e cadastre as credenciais "Dify" e "DataJud" em **Credenciais › Nova**.
5. Vá em **Cadastro de processos › Menu › Configuração**: escolha as credenciais, marque os setores e clique em
   **Testar conexão**. O esperado é "Dify: ok · DataJud: ok". Se o Dify falhar por certificado, cole a CA do
   FortiGate no campo da Configuração ou peça à TI um certificado público.
6. **Enviar PDFs**: 2 ou 3 PDFs reais (um escaneado, se tiver). Acompanhe em Envios; os dados aparecem no painel.
7. Reenvie o MESMO PDF: tem que aparecer "Já temos este arquivo … enviado por <você> em <data>".
8. **Cadastrar pelo CNJ** com um número que já existe e outro novo: a confirmação mostra quem cadastrou o existente.
9. Abra um processo, confira os campos e a caixa "Validação no CNJ", corrija algo, salve e marque como cadastrado.
10. Veja o **Log de erros e desempenho** e mande um print se algo estranho aparecer.
