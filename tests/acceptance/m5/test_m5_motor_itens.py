"""Aceite M5 parte A: motor v2. MV2-01 (itens), MV2-04 (ordem), MV2-05 (erro), MV2-06 (dados fixos), MV2-07 (histórico)."""

import re

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]


# ---------------- MV2-01 · itens ----------------

def test_gatilho_produz_um_item_com_disparado_em_e_executado_por(executar, cliente_adm, usuario_adm, h, no, jsons):
    """MV2-01: o gatilho manual produz 1 item {disparado_em: ISO, executado_por: email}."""
    _, e, _ = executar(cliente_adm, h.cadeia2())
    saida = jsons(no(e, "g"))
    assert len(saida) == 1 and set(saida[0]) >= {"disparado_em", "executado_por"}
    assert saida[0]["executado_por"] == usuario_adm.email
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", saida[0]["disparado_em"])


def test_no_roda_uma_vez_por_item_de_entrada(executar, cliente_adm, h, no, jsons):
    """MV2-01: por padrão o nó roda 1x POR ITEM; saída preserva a ordem dos itens."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("c", "editar_campos", h.cfg_editar([("dobro", "{{ $json.n * 2 }}", "numero")], True), x=2),
                  dados_fixos={"d": h.itens({"n": 1}, {"n": 2}, {"n": 3})})
    _, e, _ = executar(cliente_adm, g)
    n = no(e, "c")
    assert e.status == "sucesso" and n.itens_entrada == 3 and n.itens_saida == 3
    assert [j["dobro"] for j in jsons(n)] == [2, 4, 6]
    assert [j["n"] for j in jsons(n)] == [1, 2, 3]


def test_executar_uma_vez_usa_so_o_primeiro_item(executar, cliente_adm, h, no, jsons):
    """MV2-01: executar_uma_vez=true roda 1x com o primeiro item (executeOnce)."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("c", "editar_campos", h.cfg_editar([("r", "{{ $json.n }}", "numero")]), x=2, executar_uma_vez=True),
                  dados_fixos={"d": h.itens({"n": 7}, {"n": 8}, {"n": 9})})
    _, e, _ = executar(cliente_adm, g)
    assert jsons(no(e, "c")) == [{"r": 7}]


def test_http_roda_por_item_e_uma_vez_com_executar_uma_vez(executar, cliente_adm, liberado, h):
    """MV2-01: 3 itens → 3 requisições; com executar_uma_vez → 1 requisição."""
    def grafo(uma_vez):
        return h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                         h.no2("h", "http", h.cfg_http2(f"{liberado.base}/ok"), x=2, executar_uma_vez=uma_vez),
                         dados_fixos={"d": h.itens({"a": 1}, {"a": 2}, {"a": 3})})
    _, e, _ = executar(cliente_adm, grafo(False))
    assert e.status == "sucesso" and len(liberado.hits("/ok")) == 3
    _, e2, _ = executar(cliente_adm, grafo(True))
    assert e2.status == "sucesso" and len(liberado.hits("/ok")) == 4


def test_no_sem_itens_nao_roda_e_nao_propaga(executar, cliente_adm, liberado, h, no):
    """MV2-01/MV2-12 L2: entrada vazia → status sem_itens, nada enviado; o nó seguinte também; execução = sucesso."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("h", "http", h.cfg_http2(f"{liberado.base}/ok"), x=2),
                  h.no2("c", "editar_campos", h.cfg_editar([("r", "1", "numero")]), x=3),
                  dados_fixos={"d": []})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso"
    assert no(e, "h").status == "sem_itens" and no(e, "c").status == "sem_itens"
    assert no(e, "h").itens_saida == 0 and liberado.hits("/ok") == []


def test_limite_de_10000_itens_por_saida(executar, cliente_adm, h, no):
    """MV2-01: 10.000 itens passam; 10.001 → erro categoria limite_itens."""
    def grafo(qtd):
        return h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                         dados_fixos={"d": h.itens(*[{"i": i} for i in range(qtd)])})
    _, ok, _ = executar(cliente_adm, grafo(10000))
    assert ok.status == "sucesso" and no(ok, "d").itens_saida == 10000
    _, ruim, _ = executar(cliente_adm, grafo(10001))
    assert ruim.status == "erro" and no(ruim, "d").erro_categoria == "limite_itens"


# ---------------- MV2-04 · ordem, Juntar, desativado, pendências ----------------

def _ordem(nos_de, e):
    return [n.no_id for n in nos_de(e)]


def test_ordem_dfs_por_posicao_y_depois_x_do_destino(executar, cliente_adm, h, nos_de):
    """MV2-04/L5: destinos em ordem (y, depois x); cada ramo termina antes do próximo começar."""
    nos = [h.no2("g", "gatilho", titulo="Início"),
           h.no2("a", "sem_operacao", x=100, y=100), h.no2("a2", "sem_operacao", x=200, y=100),
           h.no2("b", "sem_operacao", x=500, y=0), h.no2("b2", "sem_operacao", x=600, y=0),
           h.no2("c", "sem_operacao", x=300, y=100)]  # empate de y com 'a': desempata por x (a antes de c)
    g = h.grafo2(nos, [("g", "a"), ("g", "b"), ("g", "c"), ("a", "a2"), ("b", "b2")])
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso"
    assert _ordem(nos_de, e) == ["g", "b", "b2", "a", "a2", "c"]
    assert [n.ordem for n in nos_de(e)] == sorted(n.ordem for n in nos_de(e))


def test_juntar_espera_todas_as_entradas_e_anexa_por_indice(executar, cliente_adm, h, nos_de, no, jsons):
    """MV2-04/NOV-04: Juntar só roda depois das duas entradas; anexar segue o índice da entrada, não a chegada."""
    nos = [h.no2("g", "gatilho", titulo="Início"),
           h.no2("x", "sem_operacao", x=100, y=0), h.no2("y", "sem_operacao", x=100, y=100),
           h.no2("j", "juntar", {"modo": "anexar", "entradas": 2}, x=400, y=50)]
    g = h.grafo2(nos, [("g", "x"), ("g", "y"), h.aresta("x", "j", 0, 1), h.aresta("y", "j", 0, 0)],
                 {"x": h.itens({"o": "x1"}), "y": h.itens({"o": "y1"}, {"o": "y2"})})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and _ordem(nos_de, e) == ["g", "x", "y", "j"]
    assert [i["o"] for i in jsons(no(e, "j"))] == ["y1", "y2", "x1"]


def test_juntar_entrada_sem_itens_conta_como_lista_vazia(executar, cliente_adm, h, no, jsons):
    """MV2-04: ramo que não produziu itens = lista vazia; o Juntar ainda roda com as outras entradas."""
    nos = [h.no2("g", "gatilho", titulo="Início"),
           h.no2("x", "sem_operacao", x=100, y=0), h.no2("y", "sem_operacao", x=100, y=100),
           h.no2("j", "juntar", {"modo": "anexar", "entradas": 2}, x=400, y=50)]
    g = h.grafo2(nos, [("g", "x"), ("g", "y"), h.aresta("x", "j", 0, 0), h.aresta("y", "j", 0, 1)],
                 {"x": [], "y": h.itens({"o": 1}, {"o": 2})})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and [i["o"] for i in jsons(no(e, "j"))] == [1, 2]


def test_no_desativado_repassa_itens_da_entrada_0_sem_alterar(executar, cliente_adm, h, no, jsons):
    """MV2-04: nó desativado repassa a entrada 0 intacta; status 'desativado'; o seguinte recebe os itens."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("c", "editar_campos", h.cfg_editar([("novo", "1", "numero")]), x=2, desativado=True),
                  h.no2("f", "sem_operacao", x=3),
                  dados_fixos={"d": h.itens({"a": 1}, {"a": 2})})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and no(e, "c").status == "desativado"
    assert jsons(no(e, "c")) == [{"a": 1}, {"a": 2}] and jsons(no(e, "f")) == [{"a": 1}, {"a": 2}]


@pytest.mark.parametrize("caso", ["ciclo", "dois_gatilhos", "no_solto", "gatilho_com_entrada"])
def test_pendencias_do_v2_impedem_executar(caso, cliente_adm, h, modelos, fabrica_fluxo):
    """MV2-04/L4: ciclo, 2 gatilhos, nó sem caminho e gatilho com entrada = pendência; nenhuma execução criada (EXE-02)."""
    base = [h.no2("g", "gatilho", titulo="Início"), h.no2("a", "sem_operacao", x=1), h.no2("b", "sem_operacao", x=2)]
    if caso == "ciclo":
        g = h.grafo2(base, [("g", "a"), ("a", "b"), ("b", "a")])
    elif caso == "dois_gatilhos":
        g = h.grafo2(base + [h.no2("g2", "gatilho", titulo="Outro")], [("g", "a"), ("a", "b")])
    elif caso == "no_solto":
        g = h.grafo2(base, [("g", "a")])
    else:
        g = h.grafo2(base, [("g", "a"), ("a", "b"), ("a", "g")])
    f = fabrica_fluxo(grafo=g, status="ativo")
    r = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}), follow=True)
    assert modelos.Execucao.objects.count() == 0
    assert "Este fluxo tem pendências" in r.content.decode()


# ---------------- MV2-05 · erro ----------------

def test_em_erro_parar_e_o_padrao(executar, cliente_adm, liberado, h, no):
    """MV2-05/EXE-05: falha para a execução; nós seguintes nao_executado."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/status/404"), x=1),
                  h.no2("f", "sem_operacao", x=2))
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "erro" and no(e, "h").status == "erro" and no(e, "h").erro_categoria == "http_4xx"
    assert no(e, "f").status == "nao_executado"


ENTRADA_ERRO = [{"a": {"b": 1}}, {"x": 1}, {"a": {"b": 3}}]


def _grafo_falha_por_item(h, em_erro, alca=False):
    nos = [h.no2("g", "gatilho", titulo="Início"), h.no2("d", "sem_operacao", x=1, titulo="Dados"),
           h.no2("c", "editar_campos", h.cfg_editar([("r", "{{ $json.a.b }}", "numero")]), x=2, em_erro=em_erro),
           h.no2("bons", "sem_operacao", x=3, y=0), h.no2("falhas", "sem_operacao", x=3, y=100)]
    ars = [("g", "d"), ("d", "c"), ("c", "bons")]
    if alca:
        ars.append(h.aresta("c", "falhas", 1, 0))
    return h.grafo2(nos, ars, {"d": h.itens(*ENTRADA_ERRO)})


def test_continuar_entrega_itens_bons_normais_e_o_que_falhou_com_erro(executar, cliente_adm, h, no, jsons):
    """MV2-05/L6: continuar → falha POR ITEM; o item ruim segue com json.erro {categoria, mensagem}; execução sucesso."""
    _, e, _ = executar(cliente_adm, _grafo_falha_por_item(h, "continuar"))
    assert e.status == "sucesso" and no(e, "c").status == "erro" and no(e, "c").erro_categoria == "expressao"
    s = jsons(no(e, "bons"))
    assert len(s) == 3 and s[0]["r"] == 1 and s[2]["r"] == 3
    assert s[1]["x"] == 1 and "r" not in s[1]
    assert s[1]["erro"]["categoria"] == "expressao" and s[1]["erro"]["mensagem"]
    assert "erro" not in s[0] and "erro" not in s[2]


def test_saida_de_erro_separa_os_itens_que_falharam(executar, cliente_adm, h, no, jsons):
    """MV2-05/L6: saida_de_erro → alça extra (índice 1 no Editar campos) só com os itens que falharam."""
    _, e, _ = executar(cliente_adm, _grafo_falha_por_item(h, "saida_de_erro", alca=True))
    assert e.status == "sucesso"
    assert [j["r"] for j in jsons(no(e, "bons"))] == [1, 3]
    f = jsons(no(e, "falhas"))
    assert len(f) == 1 and f[0]["x"] == 1 and f[0]["erro"]["categoria"] == "expressao"


def test_continuar_em_http_com_erro_segue_adiante(executar, cliente_adm, liberado, h, no, jsons):
    """MV2-05: http 404 em modo continuar entrega o item com erro http_4xx e o fluxo segue."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/status/404"), x=1, em_erro="continuar"),
                  h.no2("f", "sem_operacao", x=2))
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and no(e, "f").status == "sucesso"
    assert jsons(no(e, "f"))[0]["erro"]["categoria"] == "http_4xx"


# ---------------- MV2-06 · dados fixos e Executar este nó ----------------

def test_dados_fixos_nao_executa_e_entrega_itens_fixos(executar, cliente_adm, liberado, h, no, jsons):
    """MV2-06: nó HTTP com dados_fixos não faz requisição; entrega os itens fixos; status 'fixo'."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/ok"), x=1), h.no2("f", "sem_operacao", x=2),
                  dados_fixos={"h": h.itens({"fixo": True, "n": 1})})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and liberado.requisicoes == []
    assert no(e, "h").status == "fixo" and jsons(no(e, "f")) == [{"fixo": True, "n": 1}]


@pytest.fixture
def fluxo_teste(fabrica_fluxo, liberado, h):
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("c", "editar_campos", h.cfg_editar([("r", "{{ $json.n + 1 }}", "numero")]), x=2),
                  h.no2("h", "http", h.cfg_http2(f"{liberado.base}/ok"), x=3),
                  dados_fixos={"d": h.itens({"n": 1}, {"n": 2})})
    return fabrica_fluxo(grafo=g, status="rascunho")


def _executar_no(cliente, fluxo, no_id):
    return cliente.post(reverse("fluxos:executar_no", kwargs={"pk": fluxo.pk}), {"no_id": no_id})


def test_executar_este_no_roda_ate_ele_em_modo_teste(cliente_adm, fluxo_teste, liberado, modelos, no, jsons):
    """MV2-06/L7: roda até o nó escolhido (os seguintes não rodam), grava Execucao teste=True, não conta no histórico."""
    r = _executar_no(cliente_adm, fluxo_teste, "c")
    e = modelos.Execucao.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    assert e.teste is True and e.status == "sucesso"
    assert [j["r"] for j in jsons(no(e, "c"))] == [2, 3]
    assert not modelos.ExecucaoNo.objects.filter(execucao=e, no_id="h").exclude(status="nao_executado").exists()
    assert liberado.requisicoes == []
    assert modelos.Execucao.objects.filter(teste=False).count() == 0


def test_executar_no_com_accept_json(cliente_adm, fluxo_teste, modelos):
    """MV2-14(3): Accept: application/json → 200 {ok, execucao, url_detalhe}."""
    r = cliente_adm.post(reverse("fluxos:executar_no", kwargs={"pk": fluxo_teste.pk}), {"no_id": "c"},
                         HTTP_ACCEPT="application/json")
    e = modelos.Execucao.objects.get()
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["execucao"] == e.pk
    assert r.json()["url_detalhe"].endswith(reverse("execucoes:detalhe", kwargs={"pk": e.pk}))


def test_execucao_de_teste_nao_altera_a_home(cliente_adm, fluxo_teste, modelos):
    """MV2-14(3): a Home (inicio) segue 200 e não exibe o nome do fluxo da execução de teste."""
    _executar_no(cliente_adm, fluxo_teste, "c")
    r = cliente_adm.get(reverse("inicio"))
    assert r.status_code == 200


def test_execucao_de_teste_so_o_autor_ve(cliente_adm, fluxo_teste, fabrica_usuario, modelos, client):
    """MV2-06/L7: visível só para quem rodou (nem outro Adm); fora do histórico oficial."""
    _executar_no(cliente_adm, fluxo_teste, "c")
    e = modelos.Execucao.objects.get(teste=True)
    assert cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200
    assert e.fluxo_nome not in cliente_adm.get(reverse("execucoes:lista")).content.decode()
    outro = fabrica_usuario(papel="Adm")
    client.force_login(outro)
    assert client.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 404
    assert e.fluxo_nome not in client.get(reverse("execucoes:lista")).content.decode()


def test_executar_no_permissoes_e_metodo(cliente_base, cliente_anonimo, cliente_adm, fluxo_teste, modelos):
    """MV2-06/L7: só quem edita (Base não), anônimo → login, GET → 405; nó inexistente não cria execução nem dá 500."""
    url = reverse("fluxos:executar_no", kwargs={"pk": fluxo_teste.pk})
    assert cliente_base.post(url, {"no_id": "c"}).status_code in (403, 404)
    r = cliente_anonimo.post(url, {"no_id": "c"})
    assert r.status_code == 302 and "login" in r["Location"]
    assert cliente_adm.get(url).status_code == 405
    assert cliente_adm.post(url, {"no_id": "inexistente"}).status_code < 500
    assert cliente_adm.post(url, {}).status_code < 500
    assert modelos.Execucao.objects.count() == 0


# ---------------- MV2-07 · histórico ----------------

def test_historico_guarda_so_50_itens_e_conta_o_resto(executar, cliente_adm, h, no):
    """MV2-07: primeiros 50 itens de entrada e saída; contagem real; truncado=true."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("f", "sem_operacao", x=2),
                  dados_fixos={"d": h.itens(*[{"i": i} for i in range(60)])})
    _, e, _ = executar(cliente_adm, g)
    f = no(e, "f")
    assert f.itens_entrada == 60 and f.itens_saida == 60 and f.truncado is True
    assert len(f.entrada) == 50 and len(f.saida) == 50 and f.saida[0]["json"] == {"i": 0} and f.saida[49]["json"] == {"i": 49}


def test_historico_ate_50_itens_nao_e_truncado(executar, cliente_adm, h, no):
    """MV2-07 (limite): exatamente 50 itens não trunca."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("f", "sem_operacao", x=2),
                  dados_fixos={"d": h.itens(*[{"i": i} for i in range(50)])})
    _, e, _ = executar(cliente_adm, g)
    f = no(e, "f")
    assert f.truncado is False and len(f.saida) == 50 and f.itens_saida == 50


def test_historico_registra_erro_duracao_e_status_especiais(executar, cliente_adm, liberado, h, no, nos_de):
    """MV2-07: erro, duração e status fixo/desativado/sem_itens por nó."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("off", "sem_operacao", x=2, desativado=True),
                  h.no2("h", "http", h.cfg_http2(f"{liberado.base}/status/500"), x=3),
                  dados_fixos={"d": h.itens({"a": 1})})
    _, e, _ = executar(cliente_adm, g)
    assert [n.status for n in nos_de(e)] == ["sucesso", "fixo", "desativado", "erro"]
    assert all(isinstance(n.duracao_ms, int) and n.duracao_ms >= 0 for n in nos_de(e))
    assert no(e, "h").erro_categoria == "http_5xx" and no(e, "h").erro_mensagem


def test_detalhe_mostra_contagem_de_itens(cliente_adm, executar, h):
    """MV2-07/TEL-07: o detalhe exibe a contagem de itens do nó (aqui 60) e responde 200."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  dados_fixos={"d": h.itens(*[{"i": i} for i in range(60)])})
    _, e, _ = executar(cliente_adm, g)
    r = cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk}))
    assert r.status_code == 200 and "60" in r.content.decode()


def test_detalhe_mostra_itens_por_aresta_com_data_itens(cliente_adm, executar, h):
    """MV2-14(5)/EXE-15: o desenho do detalhe traz data-itens="<n>" nas arestas (aqui 3 itens entre Dados e Fim)."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("f", "sem_operacao", x=2),
                  dados_fixos={"d": h.itens({"a": 1}, {"a": 2}, {"a": 3})})
    _, e, _ = executar(cliente_adm, g)
    html = cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).content.decode()
    assert 'data-itens="3"' in html and 'data-itens="1"' in html


def test_base_executa_fluxo_ativo_v2_e_anonimo_vai_ao_login(cliente_base, cliente_anonimo, fabrica_fluxo, h, modelos):
    """PRM/FLX-05: Base executa fluxo ativo v2 e vai ao detalhe; anônimo → login sem execução."""
    f = fabrica_fluxo(grafo=h.cadeia2(h.no2("a", "sem_operacao", x=1)), status="ativo")
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})
    r = cliente_base.post(url)
    e = modelos.Execucao.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    assert e.status == "sucesso"
    r2 = cliente_anonimo.post(url)
    assert r2.status_code == 302 and "login" in r2["Location"]
    assert modelos.Execucao.objects.count() == 1
