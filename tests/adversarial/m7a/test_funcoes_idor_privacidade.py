"""Adversarial M7a · IDOR, escalada de papel, privacidade para_mim, CSRF e mass assignment (FUN-03/04/06/10, PRM-02/03)."""
import json

import pytest
from django.test import Client
from django.urls import reverse

from tests.acceptance.m7a.conftest import dados_funcao, entrada, grafo_func, html

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m7a")]

SEGREDO_NOME = "NOME-SECRETO-DA-FUNCAO-QQ9"


@pytest.fixture
def cenario(mundo7, criar_funcao, mk_fluxo7):
    f = mk_fluxo7(mundo7.A, grafo=grafo_func("{{ $parametros.nome }}"))
    class C: pass
    c = C()
    c.fluxo = f
    c.so_b = criar_funcao(f, nome=SEGREDO_NOME + " SoBeta", liberar_para="setores", setores=[mundo7.B.pk],
                          entradas=[entrada("nome")])
    c.so_coord = criar_funcao(f, nome=SEGREDO_NOME + " SoCoord", liberar_para="papeis", papeis=["coordenador"])
    c.inativa = criar_funcao(f, nome=SEGREDO_NOME + " Inativa", ativa=False)
    c.rascunho = criar_funcao(f, nome=SEGREDO_NOME + " Rascunho", publicar=False)
    c.aberta = criar_funcao(f, nome="Aberta", entradas=[entrada("nome")])
    return c


def _u(name, fn):
    return reverse(name, kwargs={"pk": fn.pk})


# ---------------- IDOR ----------------

@pytest.mark.parametrize("quem,alvo", [("bA", "so_b"), ("cA", "so_b"), ("bB", "so_coord"), ("bA", "so_coord"),
                                       ("bA", "inativa"), ("cA", "inativa"), ("bA", "rascunho"), ("cA", "rascunho"),
                                       ("adm", "inativa"), ("adm", "rascunho")])
def test_executar_funcao_nao_liberada_da_404_sem_vazar_e_sem_executar(mundo7, cenario, quem, alvo, modelos):
    """FUN-06: GET/POST em função fora do escopo → 404; nada executa; o nome da função não vaza na resposta."""
    fn = getattr(cenario, alvo)
    c = mundo7.c[quem]
    for r in (c.get(_u("funcoes:executar", fn)), c.post(_u("funcoes:executar", fn), {"nome": "x"})):
        assert r.status_code == 404 and SEGREDO_NOME not in html(r)
    assert modelos.Execucao.objects.count() == 0


@pytest.mark.parametrize("quem", ["bA", "cA", "bB", "bS"])
@pytest.mark.parametrize("rota", ["funcoes:editar", "funcoes:publicar", "funcoes:alternar"])
def test_gerenciar_por_nao_adm_e_negado_e_nao_altera(mundo7, cenario, quem, rota):
    """PRM-02: Base/Coordenador em editar/publicar/alternar de qualquer função → 403/404, sem alterar nada, sem vazar nome."""
    for fn in (cenario.aberta, cenario.so_b, cenario.inativa, cenario.rascunho):
        antes = (fn.versao, fn.ativa, fn.nome, json.dumps(fn.grafo_publicado, sort_keys=True))
        for r in (mundo7.c[quem].get(_u(rota, fn)), mundo7.c[quem].post(_u(rota, fn), dados_funcao(cenario.fluxo, nome="HACK"))):
            assert r.status_code in (403, 404, 405) and SEGREDO_NOME not in html(r)
        fn.refresh_from_db()
        assert (fn.versao, fn.ativa, fn.nome, json.dumps(fn.grafo_publicado, sort_keys=True)) == antes


def test_base_e_coordenador_nao_criam_funcao(mundo7, cenario, Funcao):
    """FUN-03: POST em funcoes:nova por não-Adm → 403, nada criado."""
    antes = Funcao.objects.count()
    for k in ("bA", "cA"):
        assert mundo7.c[k].post(reverse("funcoes:nova"), dados_funcao(cenario.fluxo, nome="Invasora")).status_code == 403
    assert Funcao.objects.count() == antes


def test_catalogo_e_busca_nao_vazam_funcoes_fora_do_escopo(mundo7, cenario):
    """FUN-02: ?q= com o nome de função não liberada, nem por wildcard SQL, devolve vazio para Base/Coordenador."""
    for k in ("bA", "cA"):
        for q in (SEGREDO_NOME, "NOME-SECRETO", "%", "_", "' OR 1=1 --", "SoBeta"):
            r = mundo7.c[k].get(reverse("funcoes:catalogo"), {"q": q})
            h = html(r)
            assert r.status_code == 200
            proibidos = ("SoBeta", "Inativa", "Rascunho") + (("SoCoord",) if k == "bA" else ())
            for nome in proibidos:
                assert f"{SEGREDO_NOME} {nome}" not in h, (k, q, nome)  # o campo de busca só ecoa o q, nunca o nome completo
            permitidos = {"Aberta"} | ({SEGREDO_NOME + " SoCoord"} if k == "cA" else set())
            assert {x["nome"] for x in r.context["funcoes"]} <= permitidos


@pytest.mark.parametrize("pk", ["0", "-1", "99999999999999999999", "abc", "1;DROP", "%00"])
def test_pks_estranhos_nunca_dao_500(mundo7, pk):
    """Estado inválido: pk absurdo nas rotas de função → 404 (nunca 500)."""
    for rota in ("executar", "editar", "publicar", "alternar"):
        r = mundo7.c["adm"].get(f"/funcoes/{pk}/{rota}/")
        assert r.status_code in (404, 405), (rota, pk, r.status_code)
    assert mundo7.c["adm"].get(f"/funcoes/execucoes/{pk}/").status_code == 404


# ---------------- privacidade para_mim ----------------

@pytest.fixture
def privado(mundo7, cenario, exec_funcao, modelos):
    _, e = exec_funcao(mundo7.c["bA"], cenario.aberta, {"nome": "SEGREDO-PARAMETRO-PRIVADO"})
    assert e is not None
    return e


def test_enumeracao_de_execucoes_nao_vaza_para_mim(mundo7, privado, modelos):
    """FUN-10/D-031: varrendo ids de execução, só o dono e o Adm recebem 200 (resultado e detalhe)."""
    ids = list(range(max(privado.pk - 3, 1), privado.pk + 4))
    for k in ("bA2", "bB", "cA", "cB", "bS"):
        for pk in ids:
            if pk == privado.pk:
                continue
            for rota in ("funcoes:resultado", "execucoes:detalhe"):
                r = mundo7.c[k].get(reverse(rota, kwargs={"pk": pk}))
                assert r.status_code in (404, 403, 200)
        for rota in ("funcoes:resultado", "execucoes:detalhe"):
            r = mundo7.c[k].get(reverse(rota, kwargs={"pk": privado.pk}))
            assert r.status_code == 404 and "SEGREDO-PARAMETRO-PRIVADO" not in html(r), (k, rota)


def test_para_mim_nao_aparece_em_listas_busca_home_nem_catalogo_alheios(mundo7, privado):
    """FUN-10: lista de execuções (com ?q=, ?status=, ?ordem=), Home e catálogo do Coordenador/outro Base não mostram a execução."""
    for k in ("cA", "bA2"):
        c = mundo7.c[k]
        for params in ({}, {"q": "Aberta"}, {"q": "aberta", "ordem": "-iniciada_em"}, {"status": "sucesso"}):
            r = c.get(reverse("execucoes:lista"), params)
            assert r.status_code == 200 and f"/{privado.pk}/" not in html(r) and "SEGREDO-PARAMETRO" not in html(r), (k, params)
        assert "SEGREDO-PARAMETRO" not in html(c.get(reverse("inicio")))
        ult = c.get(reverse("funcoes:catalogo")).context["funcoes"][0]["ultima"]
        assert ult is None


def test_contagem_da_home_nao_inclui_para_mim_alheio(mundo7, privado):
    """FUN-10: execucoes na Home do Coordenador do setor = 0 (a execução é privada)."""
    import re
    m = re.search(r'data-indicador="execucoes"[^>]*?data-valor="([^"]*)"', html(mundo7.c["cA"].get(reverse("inicio"))))
    assert m and float(m.group(1)) == 0


def test_execucao_modo_fluxo_nao_abre_pelo_resultado_de_outro_base(mundo7, cenario, modelos):
    """FUN-09/10: funcoes:resultado de execução de FLUXO (sem função) de outro usuário → 404; nunca 500."""
    f = cenario.fluxo
    mundo7.c["bA"].post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    e = modelos.Execucao.objects.get(modo="fluxo")
    assert mundo7.c["bA2"].get(reverse("funcoes:resultado", kwargs={"pk": e.pk})).status_code == 404
    assert mundo7.c["bA"].get(reverse("funcoes:resultado", kwargs={"pk": e.pk})).status_code in (200, 404)


def test_resultado_nao_vaza_grafo_snapshot_nem_dados_do_nos_para_base(mundo7, cenario, exec_funcao, h, liberado, criar_funcao,
                                                                      mk_fluxo7):
    """FUN-09: URL/headers/corpo das requisições internas, título de nós e snapshot não vão ao Base."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco?k=SEGREDO-URL-INTERNA", headers=[
        {"nome": "X-Interno", "valor": "SEGREDO-HEADER-INTERNO"}]), x=1, titulo="TITULO-INTERNO-ZZ"),
        h.no2("calc", "editar_campos", h.cfg_editar([("ok", "1", "texto")]), x=2, titulo="Final"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Interna")
    _, e = exec_funcao(mundo7.c["bA"], fn)
    r = mundo7.c["bA"].get(reverse("funcoes:resultado", kwargs={"pk": e.pk}))
    for s in ("SEGREDO-URL-INTERNA", "SEGREDO-HEADER-INTERNO", "TITULO-INTERNO-ZZ", "grafo_snapshot", "X-Interno"):
        assert s not in html(r), s
    ctx = r.context
    assert not any(k in ctx for k in ("requisicoes", "grafo", "nos", "logs"))


# ---------------- CSRF ----------------

@pytest.mark.parametrize("rota,quem", [("funcoes:executar", "bA"), ("funcoes:publicar", "adm"), ("funcoes:alternar", "adm"),
                                       ("funcoes:editar", "adm")])
def test_csrf_recusa_post_sem_token_em_todas_as_mutacoes(mundo7, cenario, rota, quem, modelos):
    """SEG: toda mutação de função exige CSRF (403 sem token) e não altera nada."""
    c = Client(enforce_csrf_checks=True)
    c.force_login(getattr(mundo7, quem))
    fn = cenario.aberta
    r = c.post(_u(rota, fn), dados_funcao(cenario.fluxo, nome="Mudou"))
    assert r.status_code == 403
    fn.refresh_from_db()
    assert fn.nome == "Aberta" and fn.versao == 1 and fn.ativa and modelos.Execucao.objects.count() == 0
    c2 = Client(enforce_csrf_checks=True)
    c2.force_login(mundo7.adm)
    assert c2.post(reverse("funcoes:nova"), dados_funcao(cenario.fluxo, nome="Nova CSRF")).status_code == 403


# ---------------- mass assignment ----------------

def test_mass_assignment_na_criacao_e_edicao(mundo7, cenario, Funcao, criar_funcao):
    """FUN-03/04: versao, grafo_publicado, publicada_por/em, criada_por, id enviados no POST são ignorados."""
    forjado = {"versao": 99, "grafo_publicado": json.dumps({"versao": 2, "nos": [], "arestas": []}),
               "publicada_por": mundo7.bA.pk, "publicada_em": "2020-01-01T00:00:00Z", "criada_por": mundo7.bA.pk,
               "id": 777, "pk": 777}
    r = mundo7.c["adm"].post(reverse("funcoes:nova"), dados_funcao(cenario.fluxo, nome="Forjada", **forjado))
    assert r.status_code == 302
    f = Funcao.objects.get(nome="Forjada")
    assert f.versao == 0 and f.publicada_por_id is None and f.publicada_em is None and f.pk != 777
    assert f.criada_por_id == mundo7.adm.pk and not f.grafo_publicado
    pub = cenario.aberta
    antes = json.dumps(pub.grafo_publicado, sort_keys=True)
    r = mundo7.c["adm"].post(_u("funcoes:editar", pub), dados_funcao(cenario.fluxo, nome="Aberta", **forjado))
    assert r.status_code == 302
    pub.refresh_from_db()
    assert pub.versao == 1 and json.dumps(pub.grafo_publicado, sort_keys=True) == antes
    assert pub.publicada_por_id == mundo7.adm.pk and pub.criada_por_id != mundo7.bA.pk


def test_mass_assignment_na_execucao(mundo7, cenario, exec_funcao):
    """FUN-06: campos de Execucao/Funcao no POST de executar (modo, executado_por, setor, funcao_versao, status) são ignorados."""
    _, e = exec_funcao(mundo7.c["bA"], cenario.aberta, {
        "nome": "x", "modo": "fluxo", "executado_por": mundo7.adm.pk, "setor": mundo7.B.pk, "funcao_versao": 50,
        "status": "erro", "funcao": cenario.so_b.pk, "parametros": '{"nome": "forjado"}', "grafo_snapshot": "{}"})
    assert e.modo == "para_mim" and e.executado_por_id == mundo7.bA.pk and e.setor_id == mundo7.A.pk
    assert e.funcao_id == cenario.aberta.pk and e.funcao_versao == 1 and e.status == "sucesso"
    assert e.parametros == {"nome": "x"}


def test_versao_congelada_contra_edicao_do_fluxo_por_todos_os_caminhos(mundo7, cenario, exec_funcao, h, salvar_grafo, no, jsons,
                                                                        modelos):
    """FUN-04: salvar o grafo do fluxo pelo editor (salvar_grafo) e trocar o fluxo da função não mudam a execução publicada."""
    fn = cenario.aberta
    novo = h.cadeia2(h.no2("calc", "editar_campos", h.cfg_editar([("r", "ADULTERADO", "texto")]), x=1, titulo="Calc"))
    r = salvar_grafo(mundo7.c["adm"], cenario.fluxo, novo)
    assert r.status_code == 200, r.content[:200]
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": "original"})
    assert jsons(no(e, "calc")) == [{"r": "original"}]
    outro = h.cadeia2(h.no2("calc", "editar_campos", h.cfg_editar([("r", "OUTRO", "texto")]), x=1, titulo="Calc"))
    from tests.acceptance.m7a.conftest import grafo_func as _  # noqa: F401
    f2 = modelos.Fluxo.objects.create(nome="Outro fluxo", descricao="d", dono=mundo7.adm, status="ativo", grafo=outro,
                                      setor=mundo7.A)
    mundo7.c["adm"].post(_u("funcoes:editar", fn), dados_funcao(f2, nome="Aberta", entradas=json.dumps([entrada("nome")])))
    _, e2 = exec_funcao(mundo7.c["bA"], fn, {"nome": "original"})
    assert jsons(no(e2, "calc")) == [{"r": "original"}]
