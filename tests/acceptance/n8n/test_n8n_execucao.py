"""Aceite T-073 · envio, resposta, erros, credencial, SSRF e detalhe (N8N-03..06/07). Servidor local; nada de internet."""
import json
import time
from urllib.parse import parse_qs

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("n8n")]

SEGREDO = "SEGREDO-N8N-FICTICIO-987"
MSG_404 = ("Webhook do n8n não encontrado: confira a URL e se o fluxo está ATIVO no n8n "
           "(ou em 'Listen for test event' na URL de teste).")
MSG_401 = "O n8n recusou a autenticação: confira a credencial do webhook."


def _j(n):
    return [i["json"] for i in n.saida]


# ---------------- N8N-03 · envio ----------------

def test_item_faz_uma_chamada_por_item_com_json_do_item(n8n_no, webhook, liberado, cfg):
    """N8N-03: enviar=item → UMA chamada por item; corpo = item.json; Content-Type JSON; User-Agent presente."""
    url = webhook("/webhook/a")
    e, n = n8n_no(cfg(url), [{"id": 1, "nome": "Ana"}, {"id": 2, "nome": "Bia"}])
    assert e.status == "sucesso"
    hits = liberado.hits("/webhook/a")
    assert [r["metodo"] for r in hits] == ["POST", "POST"]
    assert [json.loads(r["corpo"]) for r in hits] == [{"id": 1, "nome": "Ana"}, {"id": 2, "nome": "Bia"}]
    assert hits[0]["headers"]["content-type"].startswith("application/json")
    assert hits[0]["headers"].get("user-agent")


def test_item_e_o_padrao_quando_enviar_ausente(n8n_no, webhook, liberado, cfg):
    """N8N-01: padrão enviar=item, metodo=POST, aguardar=true."""
    url = webhook("/webhook/p")
    c = cfg(url)
    for k in ("enviar", "metodo", "aguardar_resposta", "tempo_limite_s", "corpo"):
        c.pop(k)
    e, _ = n8n_no(c, [{"a": 1}, {"a": 2}])
    assert e.status == "sucesso" and [r["metodo"] for r in liberado.hits("/webhook/p")] == ["POST", "POST"]


def test_get_sem_corpo_com_query_so_de_escalares(n8n_no, webhook, liberado, cfg):
    """N8N-03: GET → sem corpo; item.json achatado em query string só com valores escalares (lista/objeto ficam de fora)."""
    url = webhook("/webhook/g")
    n8n_no(cfg(url, metodo="GET"), [{"a": 1, "b": "x y", "c": [1, 2], "d": {"k": 1}}])
    r = liberado.hits("/webhook/g")[0]
    assert r["metodo"] == "GET" and r["corpo"] == ""
    assert r["query"] == {"a": ["1"], "b": ["x y"]}


def test_todos_faz_uma_chamada_com_itens(n8n_no, webhook, liberado, cfg):
    """N8N-03: enviar=todos → UMA chamada, corpo {"itens": [json de cada item]}."""
    url = webhook("/webhook/t")
    e, _ = n8n_no(cfg(url, enviar="todos"), [{"id": 1}, {"id": 2}, {"id": 3}])
    hits = liberado.hits("/webhook/t")
    assert e.status == "sucesso" and len(hits) == 1
    assert json.loads(hits[0]["corpo"]) == {"itens": [{"id": 1}, {"id": 2}, {"id": 3}]}


def test_sem_itens_de_entrada_nao_chama_e_saida_vazia(n8n_no, webhook, liberado, cfg):
    """N8N-03: sem itens de entrada → nenhuma chamada e saída vazia (em item e em todos)."""
    url = webhook("/webhook/v")
    for modo in ("item", "todos"):
        e, n = n8n_no(cfg(url, enviar=modo), [])
        assert e.status == "sucesso" and n.itens_saida == 0
    assert liberado.hits("/webhook/v") == []


def test_personalizado_uma_chamada_por_item_com_corpo_avaliado(n8n_no, webhook, liberado, cfg):
    """N8N-03: personalizado → UMA chamada por item, corpo = expressão avaliada (objeto)."""
    url = webhook("/webhook/c")
    e, _ = n8n_no(cfg(url, enviar="personalizado", corpo="={{ $json.dados }}"),
                  [{"id": 1, "dados": {"x": 10}}, {"id": 2, "dados": {"x": 20}}])
    assert e.status == "sucesso"
    assert [json.loads(r["corpo"]) for r in liberado.hits("/webhook/c")] == [{"x": 10}, {"x": 20}]


def test_personalizado_aceita_lista_json(n8n_no, webhook, liberado, cfg):
    """N8N-01/03: o corpo personalizado pode resultar em lista JSON."""
    url = webhook("/webhook/c2")
    n8n_no(cfg(url, enviar="personalizado", corpo="={{ $json.lista }}"), [{"lista": [1, 2, 3]}])
    assert json.loads(liberado.hits("/webhook/c2")[0]["corpo"]) == [1, 2, 3]


def test_url_aceita_expressao_por_item(n8n_no, webhook, liberado, cfg):
    """N8N-01: a URL aceita expressão, resolvida por item."""
    webhook("/webhook/e1")
    webhook("/webhook/e2")
    n8n_no(cfg(liberado.base + "/webhook/{{ $json.k }}"), [{"k": "e1"}, {"k": "e2"}])
    assert len(liberado.hits("/webhook/e1")) == 1 and len(liberado.hits("/webhook/e2")) == 1


# ---------------- N8N-04 · resposta ----------------

def test_resposta_lista_vira_itens(n8n_no, webhook, cfg):
    """N8N-04: JSON lista → um item por elemento (objeto → json; escalar → {valor: x})."""
    url = webhook("/webhook/l", corpo=[{"a": 1}, 5, "txt", {"b": 2}])
    e, n = n8n_no(cfg(url))
    assert e.status == "sucesso" and _j(n) == [{"a": 1}, {"valor": 5}, {"valor": "txt"}, {"b": 2}]


def test_resposta_objeto_vira_um_item(n8n_no, webhook, cfg):
    """N8N-04: JSON objeto → um item."""
    url = webhook("/webhook/o", corpo={"resultado": "ok", "n": 3})
    _, n = n8n_no(cfg(url))
    assert _j(n) == [{"resultado": "ok", "n": 3}]


def test_resposta_lista_vazia_gera_zero_itens(n8n_no, webhook, cfg):
    """N8N-04: lista [] → nenhum item (aplica a regra de lista)."""
    url = webhook("/webhook/lv", corpo=[])
    e, n = n8n_no(cfg(url))
    assert e.status == "sucesso" and n.itens_saida == 0


@pytest.mark.parametrize("status", [200, 202, 204])
def test_resposta_vazia_vira_n8n_status(n8n_no, liberado, cfg, status):
    """N8N-04: corpo vazio → um item {"n8n_status": <status>}."""
    liberado.rotas["/webhook/vz"] = lambda req: (status, b"", {"Content-Type": "text/plain"})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/vz"))
    assert e.status == "sucesso" and _j(n) == [{"n8n_status": status}]


def test_resposta_nao_json_vira_resposta_texto(n8n_no, liberado, cfg):
    """N8N-04: não JSON → {"resposta": texto}."""
    liberado.rotas["/webhook/tx"] = lambda req: (200, "Workflow iniciado ✓".encode(), {"Content-Type": "text/plain"})
    _, n = n8n_no(cfg(f"{liberado.base}/webhook/tx"))
    assert _j(n) == [{"resposta": "Workflow iniciado ✓"}]


def test_resposta_nao_json_grande_e_truncada_na_gravacao(n8n_no, liberado, cfg):
    """N8N-04: texto longo (200 KB, abaixo do limite de leitura) → sucesso, 1 item com 'resposta' (truncada, não maior que o original)."""
    liberado.rotas["/webhook/big"] = lambda req: (200, b"a" * 200_000, {"Content-Type": "text/plain"})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/big"))
    assert e.status == "sucesso" and n.itens_saida == 1
    assert set(_j(n)[0]) == {"resposta"} and len(_j(n)[0]["resposta"]) <= 200_000


def test_resposta_acima_de_1mb_e_resposta_grande(n8n_no, liberado, cfg):
    """N8N-07(5)/SEG-07: não JSON acima de 1 MB → erro do nó categoria resposta_grande."""
    liberado.rotas["/webhook/gg"] = lambda req: (200, b"x" * (1024 * 1024 + 5000), {"Content-Type": "text/plain"})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/gg"))
    assert e.status == "erro" and n.erro_categoria == "resposta_grande"


def test_aguardar_false_repete_entrada_com_n8n_status(n8n_no, webhook, liberado, cfg):
    """N8N-04: aguardar_resposta=false → saída repete os itens de entrada + n8n_status; corpo do n8n ignorado."""
    url = webhook("/webhook/na", status=202, corpo={"nao": "usar"})
    e, n = n8n_no(cfg(url, aguardar_resposta=False), [{"id": 1}, {"id": 2}])
    assert e.status == "sucesso"
    assert _j(n) == [{"id": 1, "n8n_status": 202}, {"id": 2, "n8n_status": 202}]
    assert len(liberado.hits("/webhook/na")) == 2


def test_aguardar_false_nao_le_corpo_gigante(n8n_no, liberado, cfg):
    """N8N-04: aguardar=false não lê o corpo além de 64 KB → corpo de 3 MB não vira erro resposta_grande."""
    liberado.rotas["/webhook/gi"] = lambda req: (200, b"z" * 3_000_000, {"Content-Type": "text/plain"})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/gi", aguardar_resposta=False), [{"id": 1}])
    assert e.status == "sucesso" and _j(n) == [{"id": 1, "n8n_status": 200}]


def test_aguardar_false_com_n8n_respondendo_erro_ainda_e_erro(n8n_no, webhook, cfg):
    """N8N-05: mesmo sem aguardar, status não-2xx continua sendo erro do nó (404 → mensagem própria)."""
    url = webhook("/webhook/na404", status=404, corpo={"message": "x"})
    e, n = n8n_no(cfg(url, aguardar_resposta=False), [{"id": 1}])
    assert e.status == "erro" and n.erro_categoria == "http_4xx" and MSG_404 in n.erro_mensagem


def test_lista_acima_do_limite_de_itens_segue_motor_v2(n8n_no, webhook, cfg):
    """N8N-04: limites de itens do motor v2 valem igual (gravação ≤ 50 itens, truncado=true, contagem real)."""
    url = webhook("/webhook/many", corpo=[{"i": i} for i in range(120)])
    e, n = n8n_no(cfg(url))
    assert e.status == "sucesso" and n.itens_saida == 120 and len(n.saida) <= 50 and n.truncado is True


# ---------------- N8N-05 · erros ----------------

def test_404_mensagem_e_categoria(n8n_no, webhook, cfg):
    """N8N-05/07: 404 → http_4xx com a mensagem exata."""
    e, n = n8n_no(cfg(webhook("/webhook/x404", status=404, corpo={"message": "not registered"})))
    assert e.status == "erro" and n.erro_categoria == "http_4xx" and MSG_404 in n.erro_mensagem


@pytest.mark.parametrize("status", [401, 403])
def test_401_e_403_recusa_de_autenticacao(n8n_no, webhook, cfg, status):
    """N8N-05/07: 401/403 → http_4xx com a mensagem de autenticação."""
    e, n = n8n_no(cfg(webhook(f"/webhook/x{status}", status=status, corpo={"message": "nope"})))
    assert e.status == "erro" and n.erro_categoria == "http_4xx" and MSG_401 in n.erro_mensagem


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_mensagem_com_status(n8n_no, webhook, cfg, status):
    """N8N-05/07: 5xx → http_5xx, 'O n8n respondeu <status>.'"""
    e, n = n8n_no(cfg(webhook(f"/webhook/x{status}", status=status, corpo={"message": "falhou"})))
    assert e.status == "erro" and n.erro_categoria == "http_5xx" and f"O n8n respondeu {status}." in n.erro_mensagem


def test_outro_4xx_mensagem_com_status(n8n_no, webhook, cfg):
    """N8N-05: outros não-2xx (ex.: 418, 422) → 'O n8n respondeu <status>.' (e não a mensagem de 404/401)."""
    e, n = n8n_no(cfg(webhook("/webhook/x422", status=422, corpo={"message": "invalido"})))
    assert e.status == "erro" and "O n8n respondeu 422." in n.erro_mensagem
    assert MSG_404 not in n.erro_mensagem and MSG_401 not in n.erro_mensagem


def test_trecho_do_corpo_do_erro_e_mascarado(n8n_no, webhook, cfg, criar_cred):
    """N8N-05: o trecho do corpo no erro é mascarado — o valor da credencial refletido pelo n8n nunca aparece."""
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)
    url = webhook("/webhook/refl", status=500, corpo={"erro": f"token recebido {SEGREDO}"})
    e, n = n8n_no(cfg(url, credencial="Cofre n8n"))
    assert e.status == "erro" and SEGREDO not in (n.erro_mensagem or "") and SEGREDO not in (e.erro_resumo or "")


def test_timeout_mensagem_exata(n8n_no, liberado, cfg):
    """N8N-05/07: tempo esgotado (tempo_limite_s=1) → categoria timeout e mensagem exata com N."""
    def lento(req):
        time.sleep(3)
        return 200, {"ok": True}, None
    liberado.rotas["/webhook/lento"] = lento
    inicio = time.monotonic()
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/lento", tempo_limite_s=1))
    assert time.monotonic() - inicio < 2.9
    assert e.status == "erro" and n.erro_categoria == "timeout"
    assert "O n8n não respondeu em 1 s. Para fluxos longos, use 'Não aguardar resposta' no nó." in n.erro_mensagem


def test_continuar_em_erro_segue_com_o_erro_no_item(n8n_no, webhook, cfg):
    """N8N-05/MV2-01: em_erro=continuar → execução segue; item de saída carrega erro{categoria,mensagem}."""
    e, n = n8n_no(cfg(webhook("/webhook/ce", status=404, corpo={"m": 1})), [{"id": 1}], em_erro="continuar")
    assert e.status == "sucesso"
    erro = _j(n)[0]["erro"]
    assert erro["categoria"] == "http_4xx" and MSG_404 in erro["mensagem"]


def test_ssrf_enderecos_internos_bloqueados(n8n_no, liberado, cfg):
    """N8N-05/SEG-01..06: endereço interno → bloqueado_ssrf, nada enviado (mesma mensagem do HTTP)."""
    for url in ("http://169.254.169.254/webhook/x", "http://localhost/webhook/x", "http://[::1]/webhook/x",
                "http://2130706433/webhook/x"):
        e, n = n8n_no(cfg(url))
        assert e.status == "erro" and n.erro_categoria == "bloqueado_ssrf", url
    assert liberado.requisicoes == []


def test_ssrf_servidor_local_sem_liberacao_e_bloqueado(n8n_no, liberado, nao_liberado, cfg):
    """N8N-05/SEG-08: n8n local que não está em MOTOR_SSRF_LIBERAR continua bloqueado."""
    nao_liberado.rotas["/webhook/x"] = lambda req: (200, {"ok": 1}, None)
    e, n = n8n_no(cfg(f"{nao_liberado.base}/webhook/x"))
    assert n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []


def test_ssrf_mensagem_igual_a_do_http(n8n_no, http_no, nao_liberado, h, cfg):
    """N8N-05: a mensagem de bloqueio é a MESMA do nó HTTP."""
    _, nh = http_no(h.cfg_http2(f"{nao_liberado.base}/x"))
    _, nn = n8n_no(cfg(f"{nao_liberado.base}/x"))
    assert nn.erro_mensagem == nh.erro_mensagem and nn.erro_mensagem


def test_url_de_expressao_que_vira_interna_e_bloqueada(n8n_no, liberado, cfg):
    """N8N-05/SEG-02: a URL resolvida de expressão também passa pelo SSRF."""
    e, n = n8n_no(cfg("{{ $json.alvo }}"), [{"alvo": "http://169.254.169.254/"}])
    assert n.erro_categoria == "bloqueado_ssrf" and liberado.requisicoes == []


# ---------------- credenciais (N8N-01/03/05/07) ----------------

def _hit(liberado, rota):
    return liberado.hits(rota)[0]


def test_credencial_bearer_aplicada(n8n_no, webhook, liberado, cfg, criar_cred):
    """N8N-03: bearer → Authorization: Bearer <valor>."""
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)
    e, _ = n8n_no(cfg(webhook("/webhook/b"), credencial="Cofre n8n"))
    assert e.status == "sucesso" and _hit(liberado, "/webhook/b")["headers"]["authorization"] == f"Bearer {SEGREDO}"


def test_credencial_cabecalho_header_auth_aplicada(n8n_no, webhook, liberado, cfg, criar_cred):
    """N8N-01/03: 'Header Auth' do n8n = credencial tipo header → o header configurado."""
    criar_cred(nome="Header Auth", tipo="header", valor=SEGREDO, header_nome="X-N8N-Chave")
    e, _ = n8n_no(cfg(webhook("/webhook/h"), credencial="Header Auth"))
    assert e.status == "sucesso" and _hit(liberado, "/webhook/h")["headers"]["x-n8n-chave"] == SEGREDO


def test_credencial_basica_aplicada(n8n_no, webhook, liberado, cfg, criar_cred):
    """N8N-01/03: basic → Authorization: Basic base64(usuario:valor)."""
    import base64
    criar_cred(nome="Basica", tipo="basic", usuario="maria", valor=SEGREDO)
    e, _ = n8n_no(cfg(webhook("/webhook/ba"), credencial="Basica"))
    esperado = "Basic " + base64.b64encode(f"maria:{SEGREDO}".encode()).decode()
    assert e.status == "sucesso" and _hit(liberado, "/webhook/ba")["headers"]["authorization"] == esperado


def test_credencial_aplicada_tambem_no_get_e_em_todos(n8n_no, webhook, liberado, cfg, criar_cred):
    """N8N-03: a credencial vale para GET e para enviar=todos."""
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)
    n8n_no(cfg(webhook("/webhook/gc"), credencial="Cofre n8n", metodo="GET"))
    n8n_no(cfg(webhook("/webhook/tc"), credencial="Cofre n8n", enviar="todos"))
    for rota in ("/webhook/gc", "/webhook/tc"):
        assert _hit(liberado, rota)["headers"]["authorization"] == f"Bearer {SEGREDO}"


def _tudo(e):
    from django.apps import apps
    partes = [json.dumps(e.grafo_snapshot, default=str), e.erro_resumo or ""]
    for x in apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e):
        partes += [json.dumps([x.entrada, x.saida, x.requisicoes], default=str), x.erro_mensagem or ""]
    return "\n".join(partes)


def test_valor_da_credencial_nunca_exposto(n8n_no, liberado, cfg, criar_cred, cliente_adm, caplog):
    """N8N-05/CRD-02: valor nunca em histórico, snapshot, saída (mesmo refletido pelo n8n), tela e log."""
    caplog.set_level("DEBUG")
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)
    liberado.rotas["/webhook/eco"] = lambda req: (200, {"recebido": req["headers"].get("authorization"), "t": SEGREDO}, None)
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/eco", credencial="Cofre n8n"))
    assert e.status == "sucesso" and liberado.hits("/webhook/eco")[0]["headers"]["authorization"] == f"Bearer {SEGREDO}"
    assert SEGREDO not in _tudo(e) and "••••" in json.dumps(n.saida, ensure_ascii=False)
    hs = {x["nome"].lower(): x["valor"] for x in n.requisicoes[0]["headers"]}
    assert hs["authorization"] == "••••"
    detalhe = cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).content.decode()
    assert SEGREDO not in detalhe and SEGREDO not in caplog.text


def test_credencial_inexistente_erro_de_execucao(n8n_no, webhook, liberado, cfg):
    """N8N-07(3): credencial inexistente → categoria credencial, mensagem exata, nada enviado."""
    e, n = n8n_no(cfg(webhook("/webhook/cf"), credencial="Fantasma"))
    assert e.status == "erro" and n.erro_categoria == "credencial"
    assert "Credencial não encontrada para este fluxo." in n.erro_mensagem and liberado.requisicoes == []


def test_credencial_tipo_incompativel(n8n_no, webhook, liberado, cfg, criar_cred):
    """N8N-07(3): credencial smtp → categoria credencial, 'Credencial do tipo … não serve para este nó.'"""
    criar_cred(nome="Correio", tipo="smtp", usuario="u", host="smtp.exemplo.test", porta="587")
    e, n = n8n_no(cfg(webhook("/webhook/cs"), credencial="Correio"))
    assert n.erro_categoria == "credencial" and n.erro_mensagem.startswith("Credencial do tipo ")
    assert "não serve para este nó." in n.erro_mensagem and liberado.requisicoes == []


def test_credencial_de_outro_setor_e_erro(cliente_adm, criar_cred, fluxo_no_setor, setor_a, setor_b, liberado, webhook, h, cfg, no, modelos):
    """N8N-02/07: fora do setor do dono do fluxo → erro 'credencial'; global e do próprio setor funcionam."""
    criar_cred(nome="DoB", setor=setor_b.pk)
    criar_cred(nome="DoA", setor=setor_a.pk)
    criar_cred(nome="Global", setor="")
    url = webhook("/webhook/set")

    def rodar(nome):
        g = h.cadeia2(h.no2("n", "chamar_n8n", cfg(url, credencial=nome), x=1))
        f = fluxo_no_setor(setor_a, grafo=g, status="ativo")
        cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
        return modelos.Execucao.objects.order_by("pk").last()

    e = rodar("DoB")
    assert e.status == "erro" and no(e, "n").erro_categoria == "credencial"
    assert no(e, "n").erro_mensagem == "Credencial não encontrada para este fluxo."
    assert rodar("DoA").status == "sucesso" and rodar("Global").status == "sucesso"


# ---------------- N8N-06 · detalhe e executar este nó ----------------

def test_requisicoes_gravadas_no_detalhe(n8n_no, webhook, cfg, cliente_adm):
    """N8N-06: requisicoes[] com método, URL, status e duração; uma por chamada; aparece no detalhe da execução."""
    url = webhook("/webhook/d", status=201, corpo={"ok": 1})
    e, n = n8n_no(cfg(url), [{"id": 1}, {"id": 2}])
    assert len(n.requisicoes) == 2
    r = n.requisicoes[0]
    assert r["metodo"] == "POST" and "/webhook/d" in r["url"] and r["status"] == 201
    assert n.duracao_ms is not None
    detalhe = cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk}))
    assert detalhe.status_code == 200 and "/webhook/d" in detalhe.content.decode()


def test_requisicao_gravada_tambem_em_erro(n8n_no, webhook, cfg):
    """N8N-06/EXE-06: a requisição é gravada com o status mesmo no erro (404)."""
    _, n = n8n_no(cfg(webhook("/webhook/de", status=404, corpo={})))
    assert n.requisicoes and n.requisicoes[0]["status"] == 404


def test_url_mascarada_no_historico_e_na_tela(n8n_no, liberado, cfg, cliente_adm):
    """N8N-06/SEG-09: parâmetro sensível na URL (api-key/token) é mascarado nas requisições e na tela."""
    liberado.rotas["/webhook/m"] = lambda req: (200, {"ok": 1}, None)
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/m?api-key={SEGREDO}&token={SEGREDO}&ok=1"))
    assert e.status == "sucesso" and SEGREDO not in json.dumps(n.requisicoes, ensure_ascii=False)
    assert SEGREDO not in cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).content.decode()


def test_executar_este_no_funciona_como_no_http(cliente_adm, fabrica_fluxo, h, cfg, webhook, liberado, modelos):
    """N8N-06/MV2-06: 'Executar este nó' → execução de teste, chamada feita, nó com sucesso."""
    url = webhook("/webhook/ex", corpo={"r": 1})
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1), h.no2("n", "chamar_n8n", cfg(url), x=2),
                  dados_fixos={"d": h.itens({"id": 7})})
    f = fabrica_fluxo(grafo=g, status="rascunho")
    r = cliente_adm.post(reverse("fluxos:executar_no", kwargs={"pk": f.pk}), {"no_id": "n"}, HTTP_ACCEPT="application/json")
    e = modelos.Execucao.objects.get(teste=True)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert json.loads(liberado.hits("/webhook/ex")[0]["corpo"]) == {"id": 7}
    assert modelos.ExecucaoNo.objects.get(execucao=e, no_id="n").status == "sucesso"


def test_no_desativado_nao_chama(n8n_no, webhook, liberado, cfg):
    """N8N-06/MV2-01: nó desativado repassa a entrada sem chamar o n8n."""
    e, n = n8n_no(cfg(webhook("/webhook/dz")), [{"id": 1}], desativado=True)
    assert n.status == "desativado" and liberado.hits("/webhook/dz") == []


def test_execucao_encadeada_usa_saida_do_n8n(executar, cliente_adm, h, cfg, webhook, no, jsons):
    """N8N-04: o resultado do n8n alimenta o nó seguinte ($json da resposta)."""
    url = webhook("/webhook/enc", corpo={"valor": 41})
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1), h.no2("n", "chamar_n8n", cfg(url), x=2),
                  h.no2("c", "editar_campos", h.cfg_editar([("r", "{{ $json.valor + 1 }}", "numero")]), x=3),
                  dados_fixos={"d": h.itens({"id": 1})})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and jsons(no(e, "c"))[0]["r"] == 42
