"""Aceite M7a · formulário de função, entradas e publicação (FUN-03, FUN-04, FUN-05, FUN-13)."""
import json

import pytest
from django.urls import reverse

from .conftest import dados_funcao, entrada, grafo_func, html, texto

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m7a")]


def _post(mundo7, d, **kw):
    return mundo7.c["adm"].post(reverse("funcoes:nova"), d, **kw)


def test_criar_feliz_nao_publica_e_redireciona_com_mensagem(mundo7, mk_fluxo7, Funcao):
    """FUN-03: salvar → redirect ao catálogo "Função salva."; versao 0; criada_por = Adm."""
    f = mk_fluxo7(mundo7.A)
    r = _post(mundo7, dados_funcao(f, nome="Minha função"), follow=True)
    assert r.redirect_chain[-1][0] == reverse("funcoes:catalogo")
    assert "Função salva." in texto(r)
    fn = Funcao.objects.get(nome="Minha função")
    assert fn.versao == 0 and fn.fluxo_id == f.pk and fn.ativa and fn.liberar_para == "todos" and fn.icone == "zap"
    assert fn.criada_por_id == mundo7.adm.pk and fn.publicada_em is None


def test_contexto_do_formulario_fun13(mundo7, mk_fluxo7):
    """FUN-13/FUN-03: formulário com `entradas_json`, `setores`, `papeis`, `icones`, `fluxos` (todos os fluxos)."""
    f1, f2 = mk_fluxo7(mundo7.A), mk_fluxo7(mundo7.B, status="rascunho")
    r = mundo7.c["adm"].get(reverse("funcoes:nova"))
    assert r.status_code == 200
    for k in ("form", "entradas_json", "setores", "papeis", "icones", "fluxos"):
        assert k in r.context, k
    assert {f1.pk, f2.pk} <= {x.pk for x in r.context["fluxos"]}
    assert set(r.context["icones"]) >= {"zap", "list-checks", "mail", "file-text", "bar-chart-3", "users", "calendar",
                                        "search", "refresh-cw", "send"}


@pytest.mark.parametrize("campos,msg", [
    ({"nome": ""}, "Informe o nome."),
    ({"nome": "   "}, "Informe o nome."),
    ({"liberar_para": "setores"}, "Escolha ao menos um setor."),
    ({"liberar_para": "papeis"}, "Escolha ao menos um papel."),
    ({"fluxo": 99999999}, "Fluxo inválido."),
    ({"fluxo": ""}, "Fluxo inválido."),
    ({"entradas": "não é json"}, "Entradas inválidas"),
])
def test_erros_do_formulario(mundo7, mk_fluxo7, Funcao, campos, msg):
    """FUN-03: mensagens exatas; 200 com o formulário; nada salvo."""
    d = dados_funcao(mk_fluxo7(mundo7.A))
    d.update(campos)
    r = _post(mundo7, d)
    assert r.status_code == 200 and msg in texto(r) and Funcao.objects.count() == 0


def test_nome_duplicado_sem_diferenciar_maiusculas(mundo7, mk_fluxo7, Funcao):
    """FUN-03: nome único sem diferenciar maiúsculas."""
    f = mk_fluxo7(mundo7.A)
    _post(mundo7, dados_funcao(f, nome="Relatório"))
    r = _post(mundo7, dados_funcao(f, nome="RELATÓRIO"))
    assert r.status_code == 200 and "Já existe uma função com este nome." in texto(r) and Funcao.objects.count() == 1


def test_limites_de_nome_e_descricao(mundo7, mk_fluxo7, Funcao):
    """FUN-03/modelo: nome ≤ 80 e descrição ≤ 300 (81/301 recusados, 80/300 aceitos); ícone fora da lista recusado."""
    f = mk_fluxo7(mundo7.A)
    assert _post(mundo7, dados_funcao(f, nome="n" * 81)).status_code == 200
    assert _post(mundo7, dados_funcao(f, nome="d", descricao="x" * 301)).status_code == 200
    assert _post(mundo7, dados_funcao(f, nome="i", icone="foguete")).status_code == 200
    assert Funcao.objects.count() == 0
    assert _post(mundo7, dados_funcao(f, nome="n" * 80, descricao="x" * 300)).status_code == 302
    assert Funcao.objects.count() == 1


def test_liberar_para_setores_e_papeis_gravam(mundo7, mk_fluxo7, Funcao):
    """FUN-03: setores (múltiplo) e papeis (múltiplo) são gravados."""
    f = mk_fluxo7(mundo7.A)
    _post(mundo7, dados_funcao(f, nome="S", liberar_para="setores", setores=[mundo7.A.pk, mundo7.B.pk]))
    _post(mundo7, dados_funcao(f, nome="P", liberar_para="papeis", papeis=["coordenador", "base"]))
    s, p = Funcao.objects.get(nome="S"), Funcao.objects.get(nome="P")
    assert {x.pk for x in s.setores.all()} == {mundo7.A.pk, mundo7.B.pk}
    assert set(p.papeis) == {"coordenador", "base"}


def test_editar_nao_publica_e_trocar_fluxo_mantem_versao_publicada(mundo7, criar_funcao, mk_fluxo7):
    """FUN-03: editar não publica; trocar o fluxo de função publicada mantém a versão e o grafo publicado."""
    f1 = mk_fluxo7(mundo7.A, grafo=grafo_func("grafo-um"))
    f2 = mk_fluxo7(mundo7.A, grafo=grafo_func("grafo-dois"))
    fn = criar_funcao(f1, nome="F Troca")
    congelado = json.dumps(fn.grafo_publicado, sort_keys=True)
    d = dados_funcao(f2, nome="F Troca", descricao="nova")
    r = mundo7.c["adm"].post(reverse("funcoes:editar", kwargs={"pk": fn.pk}), d)
    assert r.status_code == 302
    fn.refresh_from_db()
    assert fn.fluxo_id == f2.pk and fn.descricao == "nova" and fn.versao == 1
    assert json.dumps(fn.grafo_publicado, sort_keys=True) == congelado


def test_editar_proprio_nome_nao_conta_como_duplicado(mundo7, criar_funcao, mk_fluxo7):
    """FUN-03: reeditar mantendo o mesmo nome é permitido."""
    f = mk_fluxo7(mundo7.A)
    fn = criar_funcao(f, nome="Mesma")
    r = mundo7.c["adm"].post(reverse("funcoes:editar", kwargs={"pk": fn.pk}), dados_funcao(f, nome="Mesma"))
    assert r.status_code == 302


# ---------------- entradas (FUN-05) ----------------

@pytest.mark.parametrize("entradas,motivo", [
    ([entrada("dia"), entrada("dia")], "nome repetido 'dia'"),
    ([entrada("Dia")], "Entradas inválidas"),
    ([entrada("1dia")], "Entradas inválidas"),
    ([entrada("a" * 31)], "Entradas inválidas"),
    ([entrada("x", "tipo_estranho")], "Entradas inválidas"),
    ([entrada("x", "lista", opcoes=[])], "Entradas inválidas"),
    ([entrada("x", "lista", opcoes=[str(i) for i in range(51)])], "Entradas inválidas"),
    ([entrada("x", "lista", opcoes=["o" * 81])], "Entradas inválidas"),
    ([entrada(f"e{i}") for i in range(11)], "Entradas inválidas"),
    ([entrada("x", "data", padrao="31/12/2026")], "Entradas inválidas"),
    ([entrada("x", "numero", padrao="abc")], "Entradas inválidas"),
    ({"nome": "x"}, "Entradas inválidas"),
])
def test_entradas_invalidas(mundo7, mk_fluxo7, Funcao, entradas, motivo):
    """FUN-05: "Entradas inválidas: <motivo curto>." — nada salvo."""
    d = dados_funcao(mk_fluxo7(mundo7.A))
    d["entradas"] = json.dumps(entradas)
    r = _post(mundo7, d)
    assert r.status_code == 200 and "Entradas inválidas: " in texto(r) and Funcao.objects.count() == 0
    if motivo != "Entradas inválidas":
        assert f"Entradas inválidas: {motivo}." in texto(r)


def test_entradas_validas_nos_limites(mundo7, mk_fluxo7, Funcao):
    """FUN-05: 10 entradas, nome de 30 caracteres, lista com 50 opções de 80 caracteres, padrões relativos hoje/ontem."""
    ents = [entrada("a" + "b" * 29, "texto")] + [entrada(f"e{i}") for i in range(7)]
    ents += [entrada("lst", "lista", opcoes=["o" * 80] * 49 + ["u"]), entrada("dt", "data", padrao="hoje")]
    assert len(ents) == 10
    d = dados_funcao(mk_fluxo7(mundo7.A), nome="Limites")
    d["entradas"] = json.dumps(ents)
    assert _post(mundo7, d).status_code == 302
    assert len(Funcao.objects.get(nome="Limites").entradas) == 10
    d2 = dados_funcao(mk_fluxo7(mundo7.A), nome="Ontem")
    d2["entradas"] = json.dumps([entrada("dt", "data", padrao="ontem"), entrada("b", "booleano", padrao=True),
                                 entrada("n", "numero", padrao=3)])
    assert _post(mundo7, d2).status_code == 302


# ---------------- publicar (FUN-04) ----------------

def test_publicar_congela_o_grafo_e_soma_versao(mundo7, criar_funcao, mk_fluxo7, modelos):
    """FUN-04: publicar copia o grafo, versao += 1, publicada_em/por, mensagem "Versão N publicada."."""
    f = mk_fluxo7(mundo7.A, grafo=grafo_func("v1"))
    fn = criar_funcao(f, nome="F Publica", publicar=False)
    assert fn.versao == 0
    url = reverse("funcoes:publicar", kwargs={"pk": fn.pk})
    r = mundo7.c["adm"].post(url, follow=True)
    assert "Versão 1 publicada." in texto(r)
    fn.refresh_from_db()
    assert fn.versao == 1 and fn.publicada_por_id == mundo7.adm.pk and fn.publicada_em is not None
    assert fn.grafo_publicado == f.grafo
    modelos.Fluxo.objects.filter(pk=f.pk).update(grafo=grafo_func("v2"))
    fn.refresh_from_db()
    assert fn.grafo_publicado != modelos.Fluxo.objects.get(pk=f.pk).grafo  # editar o fluxo não muda a função
    r = mundo7.c["adm"].post(url, follow=True)
    assert "Versão 2 publicada." in texto(r)
    fn.refresh_from_db()
    assert fn.versao == 2 and fn.grafo_publicado == modelos.Fluxo.objects.get(pk=f.pk).grafo


def test_publicar_com_pendencia_nao_muda_nada(mundo7, criar_funcao, mk_fluxo7, modelos, h):
    """FUN-04: grafo com pendência → catálogo com a mensagem exata; versão e grafo publicado intactos."""
    f = mk_fluxo7(mundo7.A, grafo=grafo_func("ok"))
    fn = criar_funcao(f, nome="F Pendente")
    antes = fn.grafo_publicado
    ruim = h.cadeia2(h.no2("h", "http", h.cfg_http2(""), x=1, titulo="Sem URL"))
    modelos.Fluxo.objects.filter(pk=f.pk).update(grafo=ruim)
    r = mundo7.c["adm"].post(reverse("funcoes:publicar", kwargs={"pk": fn.pk}), follow=True)
    assert r.redirect_chain[-1][0] == reverse("funcoes:catalogo")
    assert "Não dá para publicar: o fluxo tem pendências. Corrija no editor." in texto(r)
    fn.refresh_from_db()
    assert fn.versao == 1 and fn.grafo_publicado == antes


def test_publicar_so_por_post(mundo7, criar_funcao, mk_fluxo7):
    """FUN-04: GET em publicar não publica."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F GetPub", publicar=False)
    r = mundo7.c["adm"].get(reverse("funcoes:publicar", kwargs={"pk": fn.pk}))
    assert r.status_code in (302, 405)
    fn.refresh_from_db()
    assert fn.versao == 0


def test_csrf_em_publicar(mundo7, criar_funcao, mk_fluxo7):
    """FUN-04/SEG: POST sem token CSRF é recusado (403) e nada muda."""
    from django.test import Client
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Csrf", publicar=False)
    c = Client(enforce_csrf_checks=True)
    c.force_login(mundo7.adm)
    assert c.post(reverse("funcoes:publicar", kwargs={"pk": fn.pk})).status_code == 403
    fn.refresh_from_db()
    assert fn.versao == 0


def test_publicar_inexistente_404(mundo7):
    """PRM-03: função inexistente → 404 com tela do produto."""
    assert mundo7.c["adm"].post(reverse("funcoes:publicar", kwargs={"pk": 999999})).status_code == 404
