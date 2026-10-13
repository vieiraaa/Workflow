"""Aceite M5 parte A: grafo v2 (MV2-02) e migração v1→v2 (MV2-03). Contrato de salvar: MV2-12 L3/L4."""

import copy
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]


@pytest.fixture
def base(h):
    return h.cadeia2(h.no2("a", "sem_operacao", x=100), h.no2("b", "sem_operacao", x=200))


@pytest.fixture
def fluxo(fabrica_fluxo, base):
    return fabrica_fluxo(grafo=base, status="rascunho")


def _salvar(salvar_grafo, cliente, fluxo, grafo, **kw):
    return salvar_grafo(cliente, fluxo, grafo, **kw)


# ---------------- MV2-02 · formato fechado v2 ----------------

def test_salva_grafo_v2_completo_e_recarrega_identico(cliente_adm, fluxo, salvar_grafo, h):
    """MV2-02/GRF-06: nós com campos novos, notas e dados_fixos salvam (200 ok) e voltam idênticos."""
    g = h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("a", "sem_operacao", x=100, y=40, desativado=True,
                                                               executar_uma_vez=True, em_erro="continuar")],
                 [("g", "a")], {"a": h.itens({"k": [1, 2, {"z": None}]})},
                 [{"id": "nt1", "texto": "# Nota\ntexto **simples**", "posicao": {"x": 10, "y": 20},
                   "tamanho": {"l": 200, "a": 100}, "cor": "azul"}])
    r = _salvar(salvar_grafo, cliente_adm, fluxo, g)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["pendencias"] == []
    fluxo.refresh_from_db()
    assert fluxo.grafo == g


@pytest.mark.parametrize("cor", ["amarela", "azul", "verde", "cinza"])
def test_cores_de_nota_aceitas(cor, cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02: as quatro cores de nota são válidas."""
    base["notas"] = [{"id": "n1", "texto": "x", "posicao": {"x": 0, "y": 0}, "tamanho": {"l": 1, "a": 1}, "cor": cor}]
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 200


@pytest.mark.parametrize("em_erro", ["parar", "continuar", "saida_de_erro"])
def test_em_erro_valores_validos(em_erro, cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02: em_erro aceita parar|continuar|saida_de_erro."""
    base["nos"][1]["em_erro"] = em_erro
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 200


def _mut_no(g): g["nos"][1]["extra"] = 1
def _mut_aresta(g): g["arestas"][0]["extra"] = 1
def _mut_raiz(g): g["extra"] = 1
def _mut_pos(g): g["nos"][1]["posicao"]["z"] = 1
def _mut_nota(g): g["notas"] = [{"id": "n1", "texto": "x", "posicao": {"x": 0, "y": 0}, "tamanho": {"l": 1, "a": 1}, "cor": "azul", "x": 1}]
def _mut_em_erro(g): g["nos"][1]["em_erro"] = "ignorar"
def _mut_cor(g): g["notas"] = [{"id": "n1", "texto": "x", "posicao": {"x": 0, "y": 0}, "tamanho": {"l": 1, "a": 1}, "cor": "rosa"}]
def _mut_saida_neg(g): g["arestas"][0]["saida"] = -1
def _mut_entrada_neg(g): g["arestas"][0]["entrada"] = -1
def _mut_saida_tipo(g): g["arestas"][0]["saida"] = "0"
def _mut_desativado_tipo(g): g["nos"][1]["desativado"] = "sim"
def _mut_pin_tipo(g): g["dados_fixos"] = {"a": {"json": {}}}
def _mut_pin_item(g): g["dados_fixos"] = {"a": [{"semjson": 1}]}
def _mut_notas_tipo(g): g["notas"] = {}
def _mut_nota_longa(g): g["notas"] = [{"id": "n1", "texto": "x" * 5001, "posicao": {"x": 0, "y": 0}, "tamanho": {"l": 1, "a": 1}, "cor": "azul"}]
def _mut_nan(g): g["nos"][1]["posicao"]["x"] = float("nan")


@pytest.mark.parametrize("mutar", [_mut_no, _mut_aresta, _mut_raiz, _mut_pos, _mut_nota, _mut_em_erro, _mut_cor,
                                   _mut_saida_neg, _mut_entrada_neg, _mut_saida_tipo, _mut_desativado_tipo,
                                   _mut_pin_tipo, _mut_pin_item, _mut_notas_tipo, _mut_nota_longa])
def test_formato_invalido_v2_e_400_sem_gravar(mutar, cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/GRF-09/L3: chave desconhecida, tipo errado, enum inválido e limite de nota = 400, nada gravado."""
    original = copy.deepcopy(fluxo.grafo)
    mutar(base)
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 400 and r.json()["ok"] is False and r.json()["erros"]
    fluxo.refresh_from_db()
    assert fluxo.grafo == original


def test_versao_desconhecida_e_400(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/L3: só versao 1 ou 2."""
    for v in (0, 3, "2", None):
        base["versao"] = v
        assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 400


def test_titulo_duplicado_e_pendencia_nao_erro(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/L3: título único no fluxo; duplicado = PENDÊNCIA (200), salva como rascunho."""
    base["nos"][2]["titulo"] = base["nos"][1]["titulo"]
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert f'Já existe um nó com o título "{base["nos"][1]["titulo"]}".' in [p["mensagem"] for p in r.json()["pendencias"]]


def test_titulo_com_mais_de_80_e_pendencia(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/GRF-04: título ≤80; 81 = pendência; 80 = ok."""
    base["nos"][1]["titulo"] = "t" * 80
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).json()["pendencias"] == []
    base["nos"][1]["titulo"] = "t" * 81
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 200 and any(p["no"] == "a" for p in r.json()["pendencias"])


def test_aresta_para_alca_inexistente_e_dados_fixos_de_no_inexistente_sao_pendencias(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/L3: saida ≥ nº de saídas do tipo e dados_fixos de nó que não existe = pendência (200)."""
    base["arestas"][1]["saida"] = 5
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 200 and "Ligação para uma saída que este nó não tem." in [p["mensagem"] for p in r.json()["pendencias"]]
    base["arestas"][1]["saida"] = 0
    base["dados_fixos"] = {"fantasma": [{"json": {}}]}
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 200 and "Dados fixos de um nó que não existe." in [p["mensagem"] for p in r.json()["pendencias"]]


def test_aresta_para_no_inexistente_e_400(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/GRF-02: aresta para nó inexistente continua sendo erro de formato."""
    base["arestas"].append({"de": "a", "saida": 0, "para": "fantasma", "entrada": 0})
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 400


def _cadeia_n(h, n):
    nos = [h.no2("g", "gatilho", titulo="Início")] + [h.no2(f"n{i}", "sem_operacao", x=i) for i in range(1, n)]
    return nos


def test_limite_de_200_nos(cliente_adm, fluxo, salvar_grafo, h):
    """MV2-02: 200 nós salvam; 201 → 400."""
    nos = _cadeia_n(h, 200)
    ids = [n["id"] for n in nos]
    g = h.grafo2(nos, list(zip(ids, ids[1:], strict=False)))
    assert _salvar(salvar_grafo, cliente_adm, fluxo, g).status_code == 200
    g2 = copy.deepcopy(g)
    g2["nos"].append(h.no2("extra", "sem_operacao", x=999))
    g2["arestas"].append(h.aresta("n199", "extra"))
    assert _salvar(salvar_grafo, cliente_adm, fluxo, g2).status_code == 400


def _arestas_distintas(ids, qtd):
    out = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            out.append((ids[i], ids[j]))
            if len(out) == qtd:
                return out
    return out


def test_limite_de_400_arestas(cliente_adm, fluxo, salvar_grafo, h):
    """MV2-02: 400 arestas salvam; 401 → 400."""
    nos = _cadeia_n(h, 40)
    ids = [n["id"] for n in nos]
    g = h.grafo2(nos, _arestas_distintas(ids, 400))
    assert _salvar(salvar_grafo, cliente_adm, fluxo, g).status_code == 200
    g2 = h.grafo2(copy.deepcopy(nos), _arestas_distintas(ids, 401))
    assert _salvar(salvar_grafo, cliente_adm, fluxo, g2).status_code == 400


def test_limite_de_100_notas(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02: 100 notas salvam; 101 → 400."""
    def nota(i):
        return {"id": f"nt{i}", "texto": "x", "posicao": {"x": 0, "y": 0}, "tamanho": {"l": 10, "a": 10}, "cor": "cinza"}
    base["notas"] = [nota(i) for i in range(100)]
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 200
    base["notas"].append(nota(100))
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 400


def test_payload_acima_de_2mb_e_400_nunca_500(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-02/SEG-14: payload > 2 MB → 400 com mensagem; um payload abaixo (~1 MB) é aceito."""
    base["dados_fixos"] = {"a": [{"json": {"t": "x" * 1_000_000}}]}
    assert _salvar(salvar_grafo, cliente_adm, fluxo, base).status_code == 200
    base["dados_fixos"] = {"a": [{"json": {"t": "x" * 2_200_000}}]}
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 400 and r.json()["erros"]


def test_json_malformado_nunca_500(cliente_adm, fluxo, salvar_grafo):
    """MV2-02/GRF-02: corpo que não é JSON → 400."""
    assert salvar_grafo(cliente_adm, fluxo, None, bruto="{nao e json").status_code == 400


def test_salvar_v2_exige_permissao(cliente_base, cliente_anonimo, fluxo, salvar_grafo, base):
    """PRM-02: Base não salva grafo (403); anônimo → login. Nada gravado."""
    original = copy.deepcopy(fluxo.grafo)
    assert salvar_grafo(cliente_base, fluxo, base).status_code in (403, 404)
    r = salvar_grafo(cliente_anonimo, fluxo, base)
    assert r.status_code in (302, 401, 403)
    fluxo.refresh_from_db()
    assert fluxo.grafo == original


def test_sem_no_saida_nao_e_pendencia_e_pode_ativar(cliente_adm, fluxo, salvar_grafo, base):
    """MV2-12 L4: Saída deixa de ser obrigatória; fluxo sem Saída ativa (FLX-04)."""
    r = _salvar(salvar_grafo, cliente_adm, fluxo, base)
    assert r.status_code == 200 and r.json()["pendencias"] == []
    r2 = cliente_adm.post(reverse("fluxos:status", kwargs={"pk": fluxo.pk}), {"status": "ativo"})
    fluxo.refresh_from_db()
    assert fluxo.status == "ativo", r2.status_code


def test_fan_out_e_varias_entradas_nao_sao_pendencia(cliente_adm, fluxo, salvar_grafo, h):
    """MV2-12 L4: fan-out e Juntar com 2 entradas são permitidos."""
    nos = [h.no2("g", "gatilho", titulo="Início"), h.no2("x", "sem_operacao", x=1), h.no2("y", "sem_operacao", x=2, y=50),
           h.no2("j", "juntar", {"modo": "anexar", "entradas": 2}, x=3)]
    g = h.grafo2(nos, [("g", "x"), ("g", "y"), h.aresta("x", "j", 0, 0), h.aresta("y", "j", 0, 1)])
    r = _salvar(salvar_grafo, cliente_adm, fluxo, g)
    assert r.status_code == 200 and r.json()["pendencias"] == []


MENSAGEM = {"ciclo": "O fluxo tem um ciclo.", "dois_gatilhos": "O fluxo precisa de exatamente um gatilho.",
            "solto": "Este nó não está ligado ao gatilho.", "gatilho_com_entrada": "O gatilho não pode ter entrada.",
            "saida_com_saida": "A Saída não pode ter ligações de saída."}


@pytest.mark.parametrize("caso", ["ciclo", "dois_gatilhos", "solto", "gatilho_com_entrada", "saida_com_saida"])
def test_pendencias_v2_na_resposta_do_salvar(caso, cliente_adm, fluxo, salvar_grafo, h):
    """MV2-04/L4: cada pendência volta em `pendencias` (200 ok=true), aponta o nó e impede ativar."""
    base = [h.no2("g", "gatilho", titulo="Início"), h.no2("a", "sem_operacao", x=1), h.no2("b", "sem_operacao", x=2)]
    if caso == "ciclo":
        g = h.grafo2(base, [("g", "a"), ("a", "b"), ("b", "a")])
    elif caso == "dois_gatilhos":
        g = h.grafo2(base + [h.no2("g2", "gatilho", titulo="Outro")], [("g", "a"), ("a", "b")])
    elif caso == "solto":
        g = h.grafo2(base, [("g", "a")])
    elif caso == "gatilho_com_entrada":
        g = h.grafo2(base, [("g", "a"), ("a", "b"), ("a", "g")])
    else:
        g = h.grafo2([base[0], base[1], h.no2("s", "saida", x=3), h.no2("t", "sem_operacao", x=4)],
                     [("g", "a"), ("a", "s"), ("s", "t")])
    r = _salvar(salvar_grafo, cliente_adm, fluxo, g)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert MENSAGEM[caso] in [p["mensagem"] for p in r.json()["pendencias"]]
    cliente_adm.post(reverse("fluxos:status", kwargs={"pk": fluxo.pk}), {"status": "ativo"})
    fluxo.refresh_from_db()
    assert fluxo.status == "rascunho"


# ---------------- MV2-03 · migração v1 → v2 ----------------

@pytest.fixture
def v1(grafo_valido_v1):
    """Grafo v1 (exemplo da spec) com placeholders anterior.* — base: grafo_valido_v1 (o grafo_valido já é v2, T-060)."""
    g = copy.deepcopy(grafo_valido_v1)
    g["nos"][1]["config"]["query"] = [{"nome": "q", "valor": "{{ anterior.executado_por }}"}]
    g["nos"].insert(2, {"id": "n4", "tipo": "http", "titulo": "Segunda", "posicao": {"x": 500, "y": 120},
                        "config": {"metodo": "GET", "url": "https://api.exemplo.test/x", "headers": [],
                                   "query": [{"nome": "id", "valor": "{{ anterior.corpo.id }}"},
                                             {"nome": "st", "valor": "{{anterior.status}}"}], "corpo": ""}})
    g["arestas"] = [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n4"}, {"de": "n4", "para": "n3"}]
    return g


def test_abrir_v1_no_editor_entrega_v2_migrado(cliente_adm, fabrica_fluxo, grafo_do_editor, v1):
    """MV2-03: ao abrir, arestas ganham saida/entrada=0, nós ganham campos novos com padrão, anterior.x → $json.x."""
    f = fabrica_fluxo(grafo=v1)
    g = grafo_do_editor(cliente_adm, f)
    assert g["versao"] == 2 and g["notas"] == [] and g["dados_fixos"] == {}
    assert all(a["saida"] == 0 and a["entrada"] == 0 for a in g["arestas"]) and len(g["arestas"]) == 3
    for n in g["nos"]:
        assert n["desativado"] is False and n["executar_uma_vez"] is False and n["em_erro"] == "parar"
    segunda = next(n for n in g["nos"] if n["id"] == "n4")
    valores = [q["valor"].replace(" ", "") for q in segunda["config"]["query"]]
    assert valores == ["{{$json.corpo.id}}", "{{$json.status}}"]
    assert segunda["config"]["resposta_completa"] is True
    assert segunda["config"]["corpo"] == {"tipo": "nenhum", "conteudo": ""}
    n2 = next(n for n in g["nos"] if n["id"] == "n2")
    assert n2["config"]["query"][0]["valor"].replace(" ", "") == "{{$json.executado_por}}"
    assert (n2["titulo"], n2["posicao"]) == ("Buscar pedido", {"x": 360, "y": 120})


def test_v1_migrado_e_aceito_ao_salvar_de_volta(cliente_adm, fabrica_fluxo, grafo_do_editor, salvar_grafo, v1):
    """MV2-03/L3: o grafo migrado que o editor entrega salva sem erro de formato."""
    f = fabrica_fluxo(grafo=v1)
    r = salvar_grafo(cliente_adm, f, grafo_do_editor(cliente_adm, f))
    assert r.status_code == 200 and r.json()["ok"] is True


def test_salvar_v1_converte_e_grava_v2(cliente_adm, fabrica_fluxo, salvar_grafo, v1):
    """MV2-03/L3: POST com versao 1 é aceito e gravado como versao 2."""
    f = fabrica_fluxo(grafo=v1)
    r = salvar_grafo(cliente_adm, f, v1)
    assert r.status_code == 200 and r.json()["ok"] is True
    f.refresh_from_db()
    assert f.grafo["versao"] == 2
    assert all("saida" in a and "entrada" in a for a in f.grafo["arestas"])
    assert "anterior" not in json.dumps(f.grafo)


def test_migra_corpo_json_nao_vazio_do_v1(cliente_adm, fabrica_fluxo, grafo_do_editor, v1):
    """MV2-14(1): corpo v1 string não vazia → {"tipo": "json", "conteudo": <mesma string>}."""
    v1["nos"][1]["config"]["metodo"] = "POST"
    v1["nos"][1]["config"]["corpo"] = '{"a": 1}'
    g = grafo_do_editor(cliente_adm, fabrica_fluxo(grafo=v1))
    n2 = next(n for n in g["nos"] if n["id"] == "n2")
    assert n2["config"]["corpo"] == {"tipo": "json", "conteudo": '{"a": 1}'}


def test_executa_fluxo_v1_com_o_mesmo_significado(cliente_adm, liberado, fabrica_fluxo, usuario_adm, modelos, no, jsons):
    """MV2-03: fluxo v1 com {{ anterior.* }} executa igual: corpo, status e campos do gatilho."""
    def noh(id_, x, url, query):
        return {"id": id_, "tipo": "http", "titulo": id_.upper(), "posicao": {"x": x, "y": 0},
                "config": {"metodo": "GET", "url": url, "headers": [], "query": query, "corpo": ""}}
    g = {"versao": 1, "nos": [
        {"id": "g", "tipo": "gatilho", "titulo": "Início", "posicao": {"x": 0, "y": 0}, "config": {}},
        noh("h1", 100, f"{liberado.base}/ok", [{"nome": "quem", "valor": "{{ anterior.executado_por }}"}]),
        noh("h2", 200, f"{liberado.base}/eco", [{"nome": "n", "valor": "{{ anterior.corpo.n }}"},
                                               {"nome": "st", "valor": "{{ anterior.status }}"}]),
        {"id": "s", "tipo": "saida", "titulo": "Saída", "posicao": {"x": 300, "y": 0}, "config": {}}],
        "arestas": [{"de": "g", "para": "h1"}, {"de": "h1", "para": "h2"}, {"de": "h2", "para": "s"}]}
    f = fabrica_fluxo(grafo=g, status="ativo")
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    e = modelos.Execucao.objects.get()
    assert e.status == "sucesso", e.erro_resumo
    assert liberado.hits("/ok")[0]["query"] == {"quem": [usuario_adm.email]}
    assert liberado.hits("/eco")[0]["query"] == {"n": ["1"], "st": ["200"]}


def test_execucao_antiga_v1_continua_legivel(cliente_adm, usuario_adm, modelos, grafo_valido_v1):
    """MV2-03: execução gravada em v1 (snapshot v1, entrada/saída objeto) abre no detalhe e na lista."""
    agora = timezone.now()
    e = modelos.Execucao.objects.create(
        fluxo=None, fluxo_nome="Fluxo Antigo Fictício", grafo_snapshot=copy.deepcopy(grafo_valido_v1), executado_por=usuario_adm,
        status="sucesso", iniciada_em=agora - timedelta(seconds=2), finalizada_em=agora, erro_resumo="")
    modelos.ExecucaoNo.objects.create(
        execucao=e, no_id="n2", no_tipo="http", no_titulo="Buscar pedido", ordem=1, status="sucesso",
        entrada={"metodo": "GET", "url": "https://api.exemplo.test/pedidos/1", "headers": [], "query": [], "corpo": ""},
        saida={"status": 200, "headers": {"content-type": "application/json"}, "corpo": {"id": 1}, "truncado": False},
        erro_categoria=None, erro_mensagem="", duracao_ms=12)
    r = cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk}))
    assert r.status_code == 200 and "Buscar pedido" in r.content.decode()
    assert "Fluxo Antigo Fictício" in cliente_adm.get(reverse("execucoes:lista")).content.decode()
