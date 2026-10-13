"""Aceite M7a · resultado e privacidade (FUN-09, FUN-10, FUN-13)."""
import json
import re

import pytest
from django.urls import reverse

from .conftest import entrada, grafo_func, html, texto

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m7a")]


def _res(e):
    return reverse("funcoes:resultado", kwargs={"pk": e.pk})


def _grafo_lista(h, n, extra=None):
    """gatilho → Dados (pin com n itens) → Editar campos (passa tudo adiante)."""
    pin = h.itens(*[{"id": i, **(extra or {})} for i in range(n)])
    return h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                     h.no2("calc", "editar_campos", h.cfg_editar([], incluir_outros=True), x=2, titulo="Calc"),
                     dados_fixos={"d": pin})


def test_resultado_rota_e_contexto_fun13(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """FUN-09/FUN-13: /funcoes/execucoes/<pk>/ com contexto funcao, execucao, parametros, colunas, linhas, total_itens,
    erro, url_detalhe (só Adm), url_executar_de_novo; mostra nome, versão e parâmetros (rótulo → valor)."""
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=grafo_func("{{ $parametros.nome }}")), nome="F Res",
                      entradas=[entrada("nome", rotulo="Seu nome")], icone="mail")
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": "Maria"})
    assert _res(e) == f"/funcoes/execucoes/{e.pk}/"
    r = mundo7.c["bA"].get(_res(e))
    assert r.status_code == 200
    c = r.context
    for k in ("funcao", "execucao", "parametros", "colunas", "linhas", "total_itens", "erro", "url_detalhe",
              "url_executar_de_novo"):
        assert k in c, k
    assert c["total_itens"] == 1 and c["colunas"] == ["r"] and c["erro"] in (None, "", False)
    assert c["url_detalhe"] in (None, "")
    t = texto(r)
    assert "F Res" in t and "Seu nome" in t and "Maria" in t and "sucesso" in t.lower()
    assert "Executar de novo" in t


def test_tabela_colunas_json_curto_e_limites(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h):
    """FUN-09: colunas = chaves do 1º nível (máx 20), valor objeto/lista → JSON curto; máx 200 linhas e
    "Mostrando 200 de N itens"."""
    g = _grafo_lista(h, 250, {f"c{i:02d}": i for i in range(24)} | {"obj": {"k": 1}, "lst": [1, 2]})
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Grande")
    _, e = exec_funcao(mundo7.c["bA"], fn)
    r = mundo7.c["bA"].get(_res(e))
    assert e.status == "sucesso" and r.context["total_itens"] == 250
    assert len(r.context["linhas"]) == 200 and len(r.context["colunas"]) == 20
    assert "Mostrando 200 de 250 itens" in texto(r)


def test_tabela_pequena_nao_mostra_aviso_e_serializa_objetos(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h):
    """FUN-09: ≤ 200 itens sem aviso; objeto/lista em célula como JSON."""
    g = _grafo_lista(h, 3, {"obj": {"k": 1}, "lst": [1, 2]})
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Pequena")
    _, e = exec_funcao(mundo7.c["bA"], fn)
    r = mundo7.c["bA"].get(_res(e))
    assert "Mostrando" not in texto(r) and len(r.context["linhas"]) == 3
    assert '{"k": 1}' in html(r).replace("&quot;", '"') or '{"k":1}' in html(r).replace("&quot;", '"')


def test_saida_e_a_do_ultimo_no_executado(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h):
    """FUN-09: a tabela mostra a saída do último nó executado."""
    g = h.cadeia2(h.no2("a", "editar_campos", h.cfg_editar([("primeiro", "1", "texto")]), x=1, titulo="A"),
                  h.no2("z", "editar_campos", h.cfg_editar([("ultimo", "2", "texto")]), x=2, titulo="Z"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Ultimo")
    _, e = exec_funcao(mundo7.c["bA"], fn)
    r = mundo7.c["bA"].get(_res(e))
    assert "ultimo" in r.context["colunas"]


def test_nao_adm_nao_ve_grafo_requisicoes_nem_intermediarios(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado):
    """FUN-09: sem canvas, grafo, requisições, logs nem nós intermediários para não-Adm; Adm vê "Detalhe técnico"."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco?marca=REQ-INTERNA-ZZ"), x=1, titulo="Chamada Interna"),
                  h.no2("calc", "editar_campos", h.cfg_editar([("final", "ok", "texto")]), x=2, titulo="Final"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Oculta")
    _, e = exec_funcao(mundo7.c["bA"], fn)
    assert e.status == "sucesso"
    r = mundo7.c["bA"].get(_res(e))
    h_base = html(r)
    for proibido in ("REQ-INTERNA-ZZ", "Chamada Interna", "drawflow", "/eco", "Detalhe técnico",
                     reverse("execucoes:detalhe", kwargs={"pk": e.pk})):
        assert proibido not in h_base, proibido
    r = mundo7.c["adm"].get(_res(e))
    assert r.status_code == 200 and "Detalhe técnico" in html(r)
    assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in html(r)
    assert r.context["url_detalhe"] == reverse("execucoes:detalhe", kwargs={"pk": e.pk})


def test_erro_mostra_categoria_e_mensagem_sem_stack(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado, no):
    """FUN-09: erro → alerta com categoria e mensagem do nó que falhou; sem stack, sem grafo."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/status/500"), x=1, titulo="Chamada Falha"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F ErroRes")
    _, e = exec_funcao(mundo7.c["bA"], fn)
    n = no(e, "h")
    r = mundo7.c["bA"].get(_res(e))
    t, h_ = texto(r), html(r)
    assert e.status == "erro" and r.context["erro"]
    assert n.erro_categoria in t or n.erro_mensagem in t
    assert "Traceback" not in h_ and 'File "' not in h_ and "drawflow" not in h_ and "/status/500" not in h_


def test_executar_de_novo_com_os_mesmos_parametros(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """FUN-09: "Executar de novo" aponta para o formulário já preenchido com os mesmos parâmetros."""
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=grafo_func("{{ $parametros.nome }}")), nome="F Denovo",
                      entradas=[entrada("nome", obrigatoria=True), entrada("cor", "lista", opcoes=["azul", "verde"])])
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": "Beatriz", "cor": "verde"})
    r = mundo7.c["bA"].get(_res(e))
    url = r.context["url_executar_de_novo"]
    assert url.startswith(reverse("funcoes:executar", kwargs={"pk": fn.pk}))
    r2 = mundo7.c["bA"].get(url)
    assert r2.status_code == 200
    campos = {c["nome"]: c["valor"] for c in r2.context["campos"]}
    assert campos["nome"] == "Beatriz" and campos["cor"] == "verde"


def test_resultado_anonimo_e_inexistente(mundo7):
    """PRM-01/PRM-03: anônimo → login; inexistente → 404."""
    assert mundo7.anon.get(reverse("funcoes:resultado", kwargs={"pk": 1})).status_code == 302
    assert mundo7.c["adm"].get(reverse("funcoes:resultado", kwargs={"pk": 999999})).status_code == 404


# ---------------- FUN-10: privacidade ----------------

@pytest.fixture
def cenario(mundo7, criar_funcao, mk_fluxo7, exec_funcao, modelos, executar):
    f = mk_fluxo7(mundo7.A)
    fn = criar_funcao(f, nome="F Privada")
    _, e_para_mim = exec_funcao(mundo7.c["bA"], fn)
    mundo7.c["bA"].post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    e_fluxo = modelos.Execucao.objects.filter(modo="fluxo", executado_por=mundo7.bA).get()
    return fn, f, e_para_mim, e_fluxo


def test_coordenador_nao_ve_execucao_para_mim_de_outro(mundo7, cenario):
    """FUN-10/D-031: Coordenador do setor → 404 no detalhe e no resultado; fora da lista; execução modo fluxo segue SET-06."""
    fn, f, e, e_fluxo = cenario
    c = mundo7.c["cA"]
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 404
    assert c.get(_res(e)).status_code == 404
    r = c.get(reverse("execucoes:lista"))
    assert e.pk not in {x.pk for x in r.context["page_obj"]} if "page_obj" in r.context else f"/{e.pk}/" not in html(r)
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": e_fluxo.pk})).status_code == 200


def test_quem_pode_ver_a_execucao_para_mim(mundo7, cenario):
    """FUN-10: o próprio executor e o Adm veem (detalhe técnico só o Adm, EXE/SET-06); outro Base não."""
    _, _, e, _ = cenario
    assert mundo7.c["bA"].get(_res(e)).status_code == 200
    assert mundo7.c["adm"].get(_res(e)).status_code == 200
    assert mundo7.c["adm"].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200
    for k in ("bA2", "bB", "cB"):
        assert mundo7.c[k].get(_res(e)).status_code == 404, k
        assert mundo7.c[k].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 404, k


def test_lista_de_execucoes_etiqueta_funcao_e_escopo(mundo7, cenario):
    """FUN-10: o executor vê a execução na lista com a etiqueta "Função"; o Adm também; Coordenador não vê."""
    fn, _, e, _ = cenario
    assert fn.nome in texto(mundo7.c["bA"].get(reverse("execucoes:lista")))
    assert fn.nome in texto(mundo7.c["adm"].get(reverse("execucoes:lista")))
    assert fn.nome not in texto(mundo7.c["cA"].get(reverse("execucoes:lista")))


def _indicador(r, chave="execucoes"):
    m = re.search(rf'data-indicador="{chave}"[^>]*?data-valor="([^"]*)"|data-valor="([^"]*)"[^>]*?data-indicador="{chave}"', html(r))
    assert m, f"indicador {chave} ausente"
    return float(m.group(1) or m.group(2))


def test_home_conta_para_mim_so_para_executor_e_adm(mundo7, cenario):
    """FUN-10: a Home conta execuções de função respeitando a regra (Coordenador não conta a para_mim de outro)."""
    _, _, e, _ = cenario
    # bA: 1 para_mim + 1 fluxo; cA (escopo setor): só a de modo fluxo; adm: as duas
    assert _indicador(mundo7.c["bA"].get(reverse("inicio"))) == 2
    assert _indicador(mundo7.c["cA"].get(reverse("inicio"))) == 1
    assert _indicador(mundo7.c["adm"].get(reverse("inicio"))) == 2


def test_coordenador_que_executa_a_propria_funcao_a_ve(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """FUN-10: o Coordenador vê as próprias execuções para_mim (resultado 200), mas não as de Base."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Coord")
    _, e = exec_funcao(mundo7.c["cA"], fn)
    assert mundo7.c["cA"].get(_res(e)).status_code == 200
    assert mundo7.c["bA"].get(_res(e)).status_code == 404
