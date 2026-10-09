"""Aceite M5 parte D: META IMP-06. Importar o exemplo n8n sanitizado, ativar os nós Código, executar contra a API Digisac FALSA
local e comparar a saída de 'Lista de chamados' com o esperado pela lógica do JSON. Nada toca a internet (fixture sem_internet).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5"), pytest.mark.usefixtures("sem_internet")]

EXEMPLO = Path(__file__).resolve().parents[3] / "docs" / "spec" / "exemplos" / "n8n_chamados_do_dia.json"
SP = ZoneInfo("America/Sao_Paulo")
CODIGOS = ("Config", "Contexto", "Lista de chamados")
HTTPS = ("Usuário do token", "Usuários", "Chamados do dia")


@pytest.fixture
def exemplo():
    return json.loads(EXEMPLO.read_text(encoding="utf-8"))


@pytest.fixture
def importar_exemplo(cliente_adm, modelos, exemplo):
    def _i():
        arq = SimpleUploadedFile("chamados.json", json.dumps(exemplo).encode(), content_type="application/json")
        r = cliente_adm.post(reverse("fluxos:importar"), {"arquivo": arq})
        assert r.status_code == 302, r.content[:300]
        return modelos.Fluxo.objects.order_by("pk").last()

    return _i


def _por_titulo(g, t):
    return next(n for n in g["nos"] if n["titulo"] == t)


def _preparar(fluxo, cliente_adm, salvar_grafo, base, por_pagina=None, ativar_codigo=True, credencial=None):
    """Como o Adm faria no editor: troca a URL base (o exemplo traz a real), ativa os Código e salva; depois ativa o fluxo."""
    g = json.loads(json.dumps(fluxo.grafo))
    cfg = _por_titulo(g, "Config")["config"]
    assert "const baseUrl = 'https://eem.digisac.co';" in cfg["codigo"]
    cfg["codigo"] = cfg["codigo"].replace("'https://eem.digisac.co'", f"'{base}'")
    if por_pagina:
        assert "porPagina: 500" in cfg["codigo"]
        cfg["codigo"] = cfg["codigo"].replace("porPagina: 500", f"porPagina: {por_pagina}")
    if credencial:
        cfg["codigo"] = cfg["codigo"].replace("'TOKEN_FICTICIO_DIGISAC'", "''")
        for t in HTTPS:
            c = _por_titulo(g, t)["config"]
            c["headers"] = [h for h in c["headers"] if h["nome"].lower() != "authorization"]
            c["credencial"] = credencial
    if ativar_codigo:
        for t in CODIGOS:
            _por_titulo(g, t)["desativado"] = False
    r = salvar_grafo(cliente_adm, fluxo, g)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["pendencias"] == [], r.content[:400]
    fluxo.refresh_from_db()
    return fluxo


def _executar(cliente_adm, fluxo, modelos):
    cliente_adm.post(reverse("fluxos:status", kwargs={"pk": fluxo.pk}), {"status": "ativo"})
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": fluxo.pk}))
    return modelos.Execucao.objects.order_by("pk").last()


def _no_exec(modelos, e, titulo):
    return modelos.ExecucaoNo.objects.get(execucao=e, no_titulo=titulo)


# ---------------- importação do exemplo ----------------

def test_importar_exemplo_mapeia_nos_arestas_e_flags(importar_exemplo, usuario_adm):
    """IMP-03/IMP-06: 6 nós nativos na ordem da cadeia, executar_uma_vez/em_erro/paginação mapeados; Código desativados; relatório."""
    f = importar_exemplo()
    g = f.grafo
    assert (f.nome, f.status, f.dono) == ("Chamados do dia (exemplo sanitizado)", "rascunho", usuario_adm) and g["versao"] == 2
    tipos = {n["titulo"]: n["tipo"] for n in g["nos"]}
    assert tipos == {"When clicking ‘Execute workflow’": "gatilho", "Config": "codigo", "Usuário do token": "http", "Contexto": "codigo",
                     "Usuários": "http", "Chamados do dia": "http", "Lista de chamados": "codigo"}
    por_id = {n["id"]: n["titulo"] for n in g["nos"]}
    cadeia = [("When clicking ‘Execute workflow’", "Config"), ("Config", "Usuário do token"), ("Usuário do token", "Contexto"),
              ("Contexto", "Usuários"), ("Usuários", "Chamados do dia"), ("Chamados do dia", "Lista de chamados")]
    assert sorted((por_id[a["de"]], por_id[a["para"]]) for a in g["arestas"]) == sorted(cadeia)
    assert all(a["saida"] == 0 and a["entrada"] == 0 for a in g["arestas"])
    for t in HTTPS[:3]:
        assert _por_titulo(g, t)["executar_uma_vez"] is True
    assert _por_titulo(g, "Usuários")["em_erro"] == "continuar"
    assert all(_por_titulo(g, t)["desativado"] is True for t in CODIGOS)
    assert sorted(f.relatorio_importacao["codigo_desativado"]) == sorted(CODIGOS)
    assert f.relatorio_importacao["segredos"] == [] and f.relatorio_importacao["sem_equivalente"] == []
    pag = _por_titulo(g, "Chamados do dia")["config"]["paginacao"]
    assert pag["modo"] == "atualizar_parametro" and pag["onde"] == "query" and pag["nome"] == "query" and pag["limite_paginas"] == 20
    assert pag["parar_quando"] == "expressao" and "$pageCount + 1" in pag["valor"] and "$response.body" in pag["expressao"]
    assert _por_titulo(g, "Usuários")["config"]["metodo"] == "GET"
    assert "/api/v1/tickets" in _por_titulo(g, "Chamados do dia")["config"]["url"]


def test_importado_nao_executa_sem_ativar_o_codigo_e_nao_toca_a_internet(importar_exemplo, cliente_adm, modelos, digisac, liberado):
    """IMP-04/IMP-06: com os Código desativados, o fluxo não chega à API (sem baseUrl) e nunca sai para a internet."""
    f = importar_exemplo()
    e = _executar(cliente_adm, f, modelos)
    assert e is not None and e.status == "erro"
    assert liberado.requisicoes == []
    assert _no_exec(modelos, e, "Config").status == "desativado"


def test_so_adm_ativa_os_codigo_do_importado(importar_exemplo, logar, setor_a, salvar_grafo, modelos):
    """IMP-04/NOV-06: Coordenador não consegue ativar o Código importado (403); nada muda."""
    f = importar_exemplo()
    modelos.Fluxo.objects.filter(pk=f.pk).update(setor=setor_a)
    f.refresh_from_db()
    g = json.loads(json.dumps(f.grafo))
    _por_titulo(g, "Config")["desativado"] = False
    cli, _ = logar("Coordenador", setor_a)
    r = salvar_grafo(cli, f, g)
    assert r.status_code == 403
    f.refresh_from_db()
    assert _por_titulo(f.grafo, "Config")["desativado"] is True


# ---------------- META: execução contra a API falsa ----------------

def test_meta_lista_de_chamados_identica_ao_esperado(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-06 (META): importar, ativar os Código, executar contra a API Digisac falsa → 'Lista de chamados' = esperado pela lógica do JSON."""
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8)
    e = _executar(cliente_adm, f, modelos)
    assert e.status == "sucesso", (e.erro_resumo, [(n.no_titulo, n.status, n.erro_categoria, n.erro_mensagem) for n in modelos.ExecucaoNo.objects.filter(execucao=e)])
    lista = _no_exec(modelos, e, "Lista de chamados")
    obtido = [i["json"] for i in lista.saida]
    esperado = digisac.esperado_lista_de_chamados(8)
    assert len(esperado) == 20 and lista.itens_saida == 20 and lista.truncado is False
    assert obtido == esperado


def test_meta_requisicoes_corretas_a_api(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-06: ordem e conteúdo das chamadas — /me, /users (1x), /tickets páginas 1..3 com janela de ontem (São Paulo), include/order/perPage."""
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8)
    e = _executar(cliente_adm, f, modelos)
    assert e.status == "sucesso"
    rotas = [r["rota"] for r in liberado.requisicoes]
    assert rotas == ["/api/v1/me", "/api/v1/users", "/api/v1/tickets", "/api/v1/tickets", "/api/v1/tickets"]
    assert all(r["headers"]["authorization"] == "Bearer TOKEN_FICTICIO_DIGISAC" and r["metodo"] == "GET" for r in liberado.requisicoes)
    assert json.loads(liberado.requisicoes[1]["query"]["query"][0]) == {"perPage": 8}
    qs = [json.loads(r["query"]["query"][0]) for r in liberado.requisicoes[2:]]
    assert [q["page"] for q in qs] == [1, 2, 3] and all(q["perPage"] == 8 for q in qs)
    agora = datetime.now(SP)
    inicio = datetime(agora.year, agora.month, agora.day, tzinfo=SP) - timedelta(days=1)
    esp_ini = inicio.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    esp_fim = (inicio.astimezone(ZoneInfo("UTC")) + timedelta(days=1) - timedelta(milliseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    for q in qs:
        assert q["where"] == {"startedAt": {"$gte": esp_ini, "$lte": esp_fim}}
        assert q["order"] == [["startedAt", "ASC"]]
        assert q["include"] == [{"model": "contact", "attributes": ["id", "name"]}, {"model": "department", "attributes": ["id", "name"]},
                                {"model": "user", "attributes": ["id", "name"]}]


def test_meta_historico_nos_ordem_status_e_mascara(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-06/MV2-07/SEG-09: 7 nós sucesso em ordem; 5 requisições gravadas; Authorization mascarado; páginas do HTTP paginado = 3 itens."""
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8)
    e = _executar(cliente_adm, f, modelos)
    nos = list(modelos.ExecucaoNo.objects.filter(execucao=e).order_by("ordem"))
    assert [n.no_titulo for n in nos] == ["When clicking ‘Execute workflow’", "Config", "Usuário do token", "Contexto", "Usuários", "Chamados do dia", "Lista de chamados"]
    assert [n.status for n in nos] == ["sucesso"] * 7
    chamados = _no_exec(modelos, e, "Chamados do dia")
    assert chamados.itens_saida == 3 and len(chamados.requisicoes) == 3
    for n in nos:
        for r in n.requisicoes or []:
            assert {x["nome"].lower(): x["valor"] for x in r["headers"]}["authorization"] == "••••"
    assert "TOKEN_FICTICIO_DIGISAC" not in json.dumps([n.requisicoes for n in nos])
    cfg = _no_exec(modelos, e, "Config").saida[0]["json"]
    assert cfg["porPagina"] == 8 and cfg["baseUrl"] == liberado.base and len(cfg["dia"]) == 10


def test_meta_com_paginacao_padrao_de_500_uma_pagina_so(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-06: com perPage 500 (padrão do exemplo) e 20 chamados, 1 página basta (<500) e a saída é a mesma lista."""
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base)
    e = _executar(cliente_adm, f, modelos)
    assert e.status == "sucesso" and [r["rota"] for r in liberado.requisicoes].count("/api/v1/tickets") == 1
    assert [i["json"] for i in _no_exec(modelos, e, "Lista de chamados").saida] == digisac.esperado_lista_de_chamados(500)


def test_meta_usuarios_com_erro_continua(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-06/MV2-05: /users falhando (500) com onError=continuar não derruba o fluxo; o resultado final é o mesmo."""
    digisac.users_status = 500
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8)
    e = _executar(cliente_adm, f, modelos)
    assert e.status == "sucesso"
    assert _no_exec(modelos, e, "Usuários").status == "erro" and _no_exec(modelos, e, "Usuários").erro_categoria == "http_5xx"
    assert [i["json"] for i in _no_exec(modelos, e, "Lista de chamados").saida] == digisac.esperado_lista_de_chamados(8)


def test_meta_token_errado_para_na_primeira_chamada(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-06/SEG-10: 401 em /me → erro http_4xx no nó 'Usuário do token'; execução erro; nada além de /me é chamado."""
    digisac.token = "OUTRO-TOKEN-FICTICIO"
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8)
    e = _executar(cliente_adm, f, modelos)
    assert e.status == "erro" and _no_exec(modelos, e, "Usuário do token").erro_categoria == "http_4xx"
    assert [r["rota"] for r in liberado.requisicoes] == ["/api/v1/me"]
    assert _no_exec(modelos, e, "Lista de chamados").status == "nao_executado"


def test_meta_com_credencial_digisac(importar_exemplo, cliente_adm, criar_cred, salvar_grafo, modelos, digisac, liberado):
    """IMP-06/CRD-02/SEG-18: credencial 'Digisac' (bearer fictício) no lugar do header Authorization → mesma lista; valor mascarado em tudo."""
    segredo = "TOKEN-DA-CREDENCIAL-FICTICIA-77"
    digisac.token = segredo
    criar_cred(nome="Digisac", valor=segredo)
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8, credencial="Digisac")
    e = _executar(cliente_adm, f, modelos)
    assert e.status == "sucesso", e.erro_resumo
    assert all(r["headers"]["authorization"] == f"Bearer {segredo}" for r in liberado.requisicoes)
    assert [i["json"] for i in _no_exec(modelos, e, "Lista de chamados").saida] == digisac.esperado_lista_de_chamados(8)
    tudo = json.dumps(list(modelos.ExecucaoNo.objects.filter(execucao=e).values("entrada", "saida", "requisicoes", "erro_mensagem")), default=str)
    tudo += json.dumps(e.grafo_snapshot) + json.dumps(f.grafo)
    assert segredo not in tudo
    assert segredo not in cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).content.decode()
    assert segredo not in cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content.decode()
    assert json.loads(cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content)["credenciais_usadas"] == ["Digisac"]


def test_meta_resultado_e_o_mesmo_via_exportar_e_reimportar(importar_exemplo, cliente_adm, salvar_grafo, modelos, digisac, liberado):
    """IMP-01+IMP-06: exportar o fluxo preparado e importar de novo (nativo) → Código volta desativado; ativado de novo roda igual."""
    f = _preparar(importar_exemplo(), cliente_adm, salvar_grafo, liberado.base, por_pagina=8)
    arq = SimpleUploadedFile("nativo.json", cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content, content_type="application/json")
    assert cliente_adm.post(reverse("fluxos:importar"), {"arquivo": arq}).status_code == 302
    g2 = modelos.Fluxo.objects.exclude(pk=f.pk).get()
    assert all(_por_titulo(g2.grafo, t)["desativado"] is True for t in CODIGOS)
    g = json.loads(json.dumps(g2.grafo))
    for t in CODIGOS:
        _por_titulo(g, t)["desativado"] = False
    assert salvar_grafo(cliente_adm, g2, g).json()["ok"] is True
    e = _executar(cliente_adm, g2, modelos)
    assert e.status == "sucesso"
    assert [i["json"] for i in _no_exec(modelos, e, "Lista de chamados").saida] == digisac.esperado_lista_de_chamados(8)
