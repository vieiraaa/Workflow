"""Aceite M3: histórico e detalhe. Fontes: EXE-03, EXE-08, EXE-09, EXE-10, EXE-07, PRM-03/04, SEG-13 (TEL-06, TEL-07)."""

import re
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _h(r):
    return r.content.decode()


@pytest.fixture
def fabrica_execucao(modelos, fabrica_fluxo, usuario_adm):
    def _criar(executado_por=None, nome="Fluxo X", status="sucesso", inicio=None, fluxo=None, grafo=None):
        inicio = inicio or timezone.now() - timedelta(minutes=1)
        return modelos.Execucao.objects.create(
            fluxo=fluxo, fluxo_nome=nome, grafo_snapshot=grafo or {"versao": 1, "nos": [], "arestas": []},
            executado_por=executado_por or usuario_adm, status=status, iniciada_em=inicio,
            finalizada_em=None if status == "executando" else inicio + timedelta(seconds=2), erro_resumo="",
        )

    return _criar


# ---------- lista ----------

@pytest.mark.modulo("m3")
def test_lista_anonimo_login(cliente_anonimo):
    """PRM-01: histórico exige login."""
    r = cliente_anonimo.get(reverse("execucoes:lista"))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador", "cliente_base"])
def test_lista_vazia_abre(request, cliente):
    """EXE-08: lista vazia responde 200 para todos os papéis."""
    assert request.getfixturevalue(cliente).get(reverse("execucoes:lista")).status_code == 200


@pytest.mark.modulo("m3")
def test_lista_mostra_colunas(cliente_adm, fabrica_execucao, usuario_coordenador):
    """EXE-08: fluxo, executado por, status, início, duração e link ao detalhe."""
    e = fabrica_execucao(executado_por=usuario_coordenador, nome="Fluxo Visivel", status="erro")
    h = _h(cliente_adm.get(reverse("execucoes:lista")))
    assert "Fluxo Visivel" in h and usuario_coordenador.nome in h
    assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in h
    assert "erro" in h.lower()


@pytest.mark.modulo("m3")
def test_base_ve_so_as_proprias(cliente_base, usuario_base, usuario_coordenador, fabrica_execucao):
    """PRM-04/EXE-08: Base só vê as próprias execuções, nem por busca, filtro ou página."""
    fabrica_execucao(executado_por=usuario_base, nome="Minha Execucao")
    for i in range(30):
        fabrica_execucao(executado_por=usuario_coordenador, nome=f"Alheia {i:02d}")
    url = reverse("execucoes:lista")
    assert "Minha Execucao" in _h(cliente_base.get(url))
    for params in ({}, {"q": "Alheia"}, {"pagina": 2}, {"status": "sucesso"}, {"ordem": "-iniciada_em"}):
        assert not re.search(r"Alheia \d\d", _h(cliente_base.get(url, params))), params


@pytest.mark.modulo("m3")
def test_coordenador_e_adm_veem_todas(cliente_coordenador, cliente_adm, usuario_base, fabrica_execucao):
    """PRM-04: escopo todos para Coordenador e Adm."""
    fabrica_execucao(executado_por=usuario_base, nome="Da Base")
    for c in (cliente_coordenador, cliente_adm):
        assert "Da Base" in _h(c.get(reverse("execucoes:lista")))


@pytest.mark.modulo("m3")
def test_busca_por_nome_do_fluxo(cliente_adm, fabrica_execucao):
    """EXE-08: ?q= por nome do fluxo, sem diferenciar maiúsculas."""
    fabrica_execucao(nome="Pedidos Quimera")
    fabrica_execucao(nome="Outro Nome")
    h = _h(cliente_adm.get(reverse("execucoes:lista"), {"q": "QUIMERA"}))
    assert "Pedidos Quimera" in h and "Outro Nome" not in h


@pytest.mark.modulo("m3")
def test_filtro_status(cliente_adm, fabrica_execucao):
    """EXE-08/EXE-11: ?status=executando|sucesso|erro."""
    fabrica_execucao(nome="Deu Certo", status="sucesso")
    fabrica_execucao(nome="Deu Erro", status="erro")
    url = reverse("execucoes:lista")
    h = _h(cliente_adm.get(url, {"status": "erro"}))
    assert "Deu Erro" in h and "Deu Certo" not in h
    h = _h(cliente_adm.get(url, {"status": "sucesso"}))
    assert "Deu Certo" in h and "Deu Erro" not in h


@pytest.mark.modulo("m3")
def test_ordenacao_padrao_mais_recente_primeiro(cliente_adm, fabrica_execucao):
    """EXE-08: padrão -iniciada_em."""
    agora = timezone.now()
    fabrica_execucao(nome="Antiga Aaa", inicio=agora - timedelta(hours=3))
    fabrica_execucao(nome="Recente Zzz", inicio=agora - timedelta(minutes=3))
    h = _h(cliente_adm.get(reverse("execucoes:lista")))
    assert h.index("Recente Zzz") < h.index("Antiga Aaa")


@pytest.mark.modulo("m3")
def test_paginacao_25(cliente_adm, fabrica_execucao):
    """EXE-08: 30 execuções → 25 na pág. 1 e 5 na pág. 2; página fora do intervalo → última."""
    agora = timezone.now()
    for i in range(30):
        fabrica_execucao(nome=f"Carga {i:02d}", inicio=agora - timedelta(minutes=i))
    url = reverse("execucoes:lista")
    cont = lambda h: len(set(re.findall(r"Carga \d\d", h)))  # noqa: E731
    assert cont(_h(cliente_adm.get(url, {"q": "Carga"}))) == 25
    assert cont(_h(cliente_adm.get(url, {"q": "Carga", "pagina": 2}))) == 5
    assert cont(_h(cliente_adm.get(url, {"q": "Carga", "pagina": 99}))) == 5


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("params", [{"status": "x"}, {"ordem": "grafo_snapshot"}, {"ordem": "executado_por__password"}, {"pagina": "abc"}, {"pagina": "-1"}, {"q": "%" * 300}, {"q": "\x00"}])
def test_parametros_invalidos_nunca_500(cliente_adm, params):
    """EXE-08: valores inválidos de filtro/ordem/página/busca são ignorados."""
    assert cliente_adm.get(reverse("execucoes:lista"), params).status_code == 200


@pytest.mark.modulo("m3")
def test_queries_da_lista_constantes(cliente_adm, fabrica_execucao, django_assert_max_num_queries):
    """EXE-08: nº de queries com 30 execuções ≤ nº com 1 (sem N+1)."""
    fabrica_execucao(nome="Primeira")
    url = reverse("execucoes:lista")
    cliente_adm.get(url)
    with CaptureQueriesContext(connection) as base:
        cliente_adm.get(url)
    for i in range(29):
        fabrica_execucao(nome=f"Mais {i}")
    with django_assert_max_num_queries(len(base.captured_queries)):
        assert cliente_adm.get(url).status_code == 200


# ---------- detalhe ----------

@pytest.mark.modulo("m3")
def test_detalhe_mostra_cabecalho_e_nos_em_ordem(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """EXE-09: cabeçalho (fluxo, status, quem) e nós em ordem com entrada/saída."""
    g = cadeia(cfg_http(f"{liberado.base}/eco", query=[{"nome": "marca", "valor": "VALORDETESTE"}]))
    titulos = ["Disparo Inicial Unico", "Consulta Intermediaria Unica", "Resultado Final Unico"]
    for n, t in zip(g["nos"], titulos, strict=True):
        n["titulo"] = t
    _, e, f = executar(cliente_coordenador, g)
    h = _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert f.nome in h and e.executado_por.nome in h
    assert all(h.count(t) >= 1 for t in titulos)
    assert h.index(titulos[0]) < h.index(titulos[1]) < h.index(titulos[2])
    assert "VALORDETESTE" in h and "200" in h


@pytest.mark.modulo("m3")
def test_detalhe_exibe_erro_do_no(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """EXE-09/SEG-10: o detalhe mostra a mensagem própria do erro e o corpo da resposta de diagnóstico."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/status/500")))
    h = _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert no(e, "h1").erro_mensagem in h
    assert "detalhe do servidor" in h


@pytest.mark.modulo("m3")
def test_detalhe_tem_botao_copiar_para_a_saida(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """EXE-07: resultado da saída em bloco JSON com botão copiar."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/ok")))
    h = _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert "Copiar" in h or "copiar" in h.lower()


@pytest.mark.modulo("m3")
def test_detalhe_escapa_corpo_hostil_da_resposta(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """SEG-13: corpo HTML/JS de resposta HTTP aparece escapado no detalhe."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/xss")))
    h = _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert "<script>window.__pwn=1</script>" not in h
    assert "<img src=x onerror" not in h
    assert "&lt;script&gt;" in h


@pytest.mark.modulo("m3")
def test_detalhe_escopo_base_404_para_alheia(cliente_base, usuario_coordenador, usuario_base, fabrica_execucao):
    """PRM-03: Base abrindo execução de outro → 404; a própria → 200; pk inexistente → 404."""
    alheia = fabrica_execucao(executado_por=usuario_coordenador)
    propria = fabrica_execucao(executado_por=usuario_base)
    assert cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": alheia.pk})).status_code == 404
    assert cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": propria.pk})).status_code == 200
    assert cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": 999999})).status_code == 404


@pytest.mark.modulo("m3")
def test_detalhe_coordenador_ve_de_outros_e_anonimo_vai_ao_login(cliente_coordenador, cliente_anonimo, usuario_base, fabrica_execucao):
    """PRM-01/PRM-04: Coordenador abre execução de outro; anônimo → login."""
    e = fabrica_execucao(executado_por=usuario_base)
    url = reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    assert cliente_coordenador.get(url).status_code == 200
    r = cliente_anonimo.get(url)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


# ---------- EXE-03: snapshot e fluxo excluído ----------

@pytest.mark.modulo("m3")
def test_editar_ou_excluir_o_fluxo_nao_altera_o_historico(cliente_coordenador, liberado, executar, cadeia, cfg_http, modelos, no):
    """EXE-03/FLX-03: snapshot do grafo; fluxo excluído vira nulo e a execução guarda o nome; detalhe e lista seguem funcionando."""
    g = cadeia(cfg_http(f"{liberado.base}/ok"))
    _, e, f = executar(cliente_coordenador, g)
    snapshot = e.grafo_snapshot
    nome = f.nome
    cliente_coordenador.post(reverse("fluxos:editar", kwargs={"pk": f.pk}), {"nome": "Renomeado", "descricao": ""})
    f.refresh_from_db()
    f.grafo = {"versao": 1, "nos": [], "arestas": []}
    f.save()
    e.refresh_from_db()
    assert e.grafo_snapshot == snapshot and e.fluxo_nome == nome
    assert cliente_coordenador.post(reverse("fluxos:excluir", kwargs={"pk": f.pk})).status_code == 302
    e.refresh_from_db()
    assert e.fluxo_id is None and e.fluxo_nome == nome and e.grafo_snapshot == snapshot
    assert no(e, "h1").status == "sucesso"
    assert nome in _h(cliente_coordenador.get(reverse("execucoes:lista")))
    assert cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200


# ---------- EXE-10 ----------

@pytest.mark.modulo("m3")
def test_executando_ha_mais_de_5_min_aparece_como_erro_interrompida(cliente_adm, fabrica_execucao):
    """EXE-10: 'executando' por mais de 5 min é exibida como erro com resumo 'Execução interrompida'."""
    antiga = fabrica_execucao(nome="Travada Zzz", status="executando", inicio=timezone.now() - timedelta(minutes=6))
    h = _h(cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": antiga.pk})))
    assert "Execução interrompida" in h
    lista = _h(cliente_adm.get(reverse("execucoes:lista"), {"status": "erro"}))
    assert "Travada Zzz" in lista


@pytest.mark.modulo("m3")
def test_executando_ha_menos_de_5_min_continua_executando(cliente_adm, fabrica_execucao):
    """EXE-10 (limite): com 4 min ainda é 'executando' e sem o resumo de interrupção."""
    recente = fabrica_execucao(nome="Rodando Aaa", status="executando", inicio=timezone.now() - timedelta(minutes=4))
    h = _h(cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": recente.pk})))
    assert "Execução interrompida" not in h
    assert "Rodando Aaa" in _h(cliente_adm.get(reverse("execucoes:lista"), {"status": "executando"}))
