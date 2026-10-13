"""Aceite M5 parte B: nós de fluxo (NOV-04: Juntar, Repetir em lotes, Parar com erro, Sem operação). MV2-15 B4, B5."""

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

A = [{"id": 1, "a": "x", "v": "da-A"}, {"id": 2, "a": "y", "v": "da-A"}]
B = [{"k": 2, "b": "Y", "v": "da-B"}, {"k": 3, "b": "Z", "v": "da-B"}]


@pytest.fixture
def juntar(executar, cliente_adm, h, no, jsons):
    """juntar(config, itens_entrada0, itens_entrada1[, itens_entrada2]) → (execucao, itens da saída do Juntar)."""

    def _j(cfg, *entradas):
        nos = [h.no2("g", "gatilho", titulo="Início")]
        ars, pins = [], {}
        for i, ent in enumerate(entradas):
            nos.append(h.no2(f"e{i}", "sem_operacao", x=1, y=i * 100, titulo=f"E{i}"))
            ars += [("g", f"e{i}"), h.aresta(f"e{i}", "j", 0, i)]
            pins[f"e{i}"] = h.itens(*ent)
        nos.append(h.no2("j", "juntar", {"entradas": max(2, len(entradas)), **cfg}, x=2, y=50, titulo="Juntar"))
        _, e, _ = executar(cliente_adm, h.grafo2(nos, ars, pins))
        assert e.status == "sucesso", e.erro_resumo
        return e, jsons(no(e, "j"))

    return _j


M1 = {"id": 2, "a": "y", "k": 2, "b": "Y", "v": "da-B"}


@pytest.mark.parametrize("tipo,esperado", [
    ("dentro", [M1]),
    ("esquerda", [{"id": 1, "a": "x", "v": "da-A"}, M1]),
    ("direita", [M1, {"k": 3, "b": "Z", "v": "da-B"}]),
    ("externa", [{"id": 1, "a": "x", "v": "da-A"}, M1, {"k": 3, "b": "Z", "v": "da-B"}]),
])
def test_juntar_combinar_por_campo(tipo, esperado, juntar):
    """NOV-04/B4: dentro/esquerda/direita/externa; mescla {**entrada0, **entrada1} (a entrada 1 vence)."""
    _, s = juntar({"modo": "combinar_por_campo", "campo1": "id", "campo2": "k", "tipo": tipo}, A, B)
    assert s == esperado  # MV2-17: ordem da entrada 0; só-da-direita depois, na ordem da entrada 1


def test_juntar_combinar_por_posicao_ate_o_menor(juntar):
    """NOV-04/B4: pares por índice até o menor tamanho."""
    _, s = juntar({"modo": "combinar_por_posicao"}, [{"a": 1}, {"a": 2}, {"a": 3}], [{"b": "x"}, {"b": "y"}])
    assert s == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_juntar_escolher_entrada_0_based(juntar):
    """NOV-04/B4: escolher_entrada com índice 0-based."""
    _, s0 = juntar({"modo": "escolher_entrada", "entrada": 0}, A, B)
    _, s1 = juntar({"modo": "escolher_entrada", "entrada": 1}, A, B)
    assert s0 == A and s1 == B


def test_juntar_anexar_com_tres_entradas(juntar):
    """NOV-04: entradas 2..4; anexar põe todas em sequência pela ordem das entradas."""
    _, s = juntar({"modo": "anexar"}, [{"o": 1}], [{"o": 2}], [{"o": 3}])
    assert [j["o"] for j in s] == [1, 2, 3]


@pytest.mark.parametrize("entradas", [1, 5])
def test_juntar_entradas_fora_de_2_a_4_e_pendencia(entradas, cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-04: 'entradas' precisa estar em 2..4 (pendência, 200)."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    g = h.grafo2([h.no2("g", "gatilho", titulo="Início"), h.no2("j", "juntar", {"modo": "anexar", "entradas": entradas}, x=1)], [("g", "j")])
    r = salvar_grafo(cliente_adm, f, g)
    assert r.status_code == 200 and r.json()["pendencias"]


# ---------------- Repetir em lotes ----------------

def _grafo_lotes(h, qtd, tamanho=2, com_corpo=True):
    nos = [h.no2("g", "gatilho", titulo="Início"), h.no2("d", "sem_operacao", x=1, titulo="Dados"),
           h.no2("l", "repetir_em_lotes", {"tamanho_lote": tamanho}, x=2, titulo="Lotes"),
           h.no2("corpo", "editar_campos", h.cfg_editar([("visto", "1", "numero")], True), x=3, y=0, titulo="Corpo"),
           h.no2("fim", "sem_operacao", x=3, y=100, titulo="Fim")]
    ars = [("g", "d"), ("d", "l"), h.aresta("l", "corpo", 0, 0), h.aresta("corpo", "l", 0, 0), h.aresta("l", "fim", 1, 0)]
    return h.grafo2(nos, ars, {"d": h.itens(*[{"i": i} for i in range(qtd)])})


def test_laco_de_repetir_em_lotes_nao_e_pendencia(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    """NOV-04/L4: a aresta de retorno para o próprio Repetir em lotes é a única volta permitida (sem pendência de ciclo)."""
    f = fabrica_fluxo(grafo=h.cadeia2())
    r = salvar_grafo(cliente_adm, f, _grafo_lotes(h, 5))
    assert r.status_code == 200 and r.json()["pendencias"] == []


def test_repetir_em_lotes_executa_o_corpo_por_lote_e_entrega_tudo_ao_fim(executar, cliente_adm, h, modelos, jsons):
    """NOV-04/B5: 5 itens em lotes de 2 → corpo roda 3x (2, 2, 1 itens); 'pronto' recebe os 5 que voltaram; 1 ExecucaoNo por visita."""
    _, e, _ = executar(cliente_adm, _grafo_lotes(h, 5))
    assert e.status == "sucesso", e.erro_resumo
    corpo = list(modelos.ExecucaoNo.objects.filter(execucao=e, no_id="corpo").order_by("ordem"))
    assert [n.itens_entrada for n in corpo] == [2, 2, 1]
    assert [[j["i"] for j in jsons(n)] for n in corpo] == [[0, 1], [2, 3], [4]]
    fim = modelos.ExecucaoNo.objects.get(execucao=e, no_id="fim")
    assert [j["i"] for j in jsons(fim)] == [0, 1, 2, 3, 4] and all(j["visto"] == 1 for j in jsons(fim))
    ordens = list(modelos.ExecucaoNo.objects.filter(execucao=e).order_by("ordem").values_list("ordem", flat=True))
    assert ordens == sorted(set(ordens))
    assert modelos.ExecucaoNo.objects.filter(execucao=e, no_id="fim").count() == 1


def test_repetir_em_lotes_lote_maior_que_o_total_roda_uma_vez(executar, cliente_adm, h, modelos):
    """NOV-04: lote ≥ total → 1 volta só."""
    _, e, _ = executar(cliente_adm, _grafo_lotes(h, 3, tamanho=10))
    assert e.status == "sucesso" and modelos.ExecucaoNo.objects.filter(execucao=e, no_id="corpo").count() == 1


def test_repetir_em_lotes_sem_itens(executar, cliente_adm, h, no):
    """MV2-01+NOV-04: sem itens de entrada o nó não roda (sem_itens) e o corpo também não."""
    _, e, _ = executar(cliente_adm, _grafo_lotes(h, 0))
    assert e.status == "sucesso" and no(e, "l").status == "sem_itens"


def test_repetir_em_lotes_passa_do_limite_de_1000_voltas(executar, cliente_adm, h, modelos):
    """NOV-04/B5: mais de 1.000 voltas → erro categoria laco_excessivo; abaixo do limite roda."""
    _, ok, _ = executar(cliente_adm, _grafo_lotes(h, 300, tamanho=1))
    assert ok.status == "sucesso"
    _, ruim, _ = executar(cliente_adm, _grafo_lotes(h, 1100, tamanho=1))
    assert ruim.status == "erro"
    assert modelos.ExecucaoNo.objects.filter(execucao=ruim, erro_categoria="laco_excessivo").exists()


# ---------------- Parar com erro / Sem operação ----------------

def test_parar_com_erro_usa_a_mensagem_resolvida(executar, cliente_adm, h, no):
    """NOV-04/L12: Parar com erro → categoria 'parado', mensagem = expressão resolvida; seguintes nao_executado."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("p", "parar_com_erro", {"mensagem": "Falhou no pedido {{ $json.id }}"}, x=2),
                  h.no2("f", "sem_operacao", x=3), dados_fixos={"d": h.itens({"id": 7})})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "erro" and no(e, "p").erro_categoria == "parado"
    assert "Falhou no pedido 7" in no(e, "p").erro_mensagem and "Falhou no pedido 7" in e.erro_resumo
    assert no(e, "f").status == "nao_executado"


def test_parar_com_erro_em_ramo_sem_itens_nao_dispara(executar, cliente_adm, h, no):
    """MV2-01+NOV-04: ramo vazio (sem_itens) nunca chega a parar a execução."""
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("p", "parar_com_erro", {"mensagem": "x"}, x=2), dados_fixos={"d": []})
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and no(e, "p").status == "sem_itens"


def test_sem_operacao_repassa_os_itens(rodar_no):
    """NOV-04: Sem operação entrega os mesmos itens."""
    ent = [{"a": 1}, {"b": [1, 2]}]
    _, (s,) = rodar_no("sem_operacao", {}, ent)
    assert s == ent
