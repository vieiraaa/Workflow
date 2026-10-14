"""Aceite M7a · catálogo, liberação e permissões (FUN-01, FUN-02, FUN-13, permissoes funcoes.*)."""
import pytest
from django.urls import reverse

from .conftest import entrada, html, texto

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m7a")]


def _nomes(r):
    return [f["nome"] for f in r.context["funcoes"]]


def test_menu_tem_item_funcoes_para_todos_os_papeis(mundo7, criar_funcao, mk_fluxo7):
    """FUN-01: item "Funções" no menu (ícone square-function) para quem tem funcoes.ver; rota /funcoes/."""
    assert reverse("funcoes:catalogo") == "/funcoes/"
    for k in ("adm", "cA", "bA"):
        r = mundo7.c[k].get(reverse("inicio"))
        h = html(r)
        assert "Funções" in h and "square-function" in h and reverse("funcoes:catalogo") in h
        assert h.index("Início") < h.index("Funções")


def test_anonimo_vai_para_login(mundo7):
    """PRM-01: anônimo no catálogo → 302 login?next."""
    r = mundo7.anon.get(reverse("funcoes:catalogo"))
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))


def test_catalogo_por_papel_e_liberacao(mundo7, criar_funcao, mk_fluxo7):
    """FUN-02/escopo_liberadas: todos / setores / papeis; usuário sem setor só vê todos/papel."""
    f = mk_fluxo7(mundo7.A)
    todos = criar_funcao(f, nome="F Todos")
    so_a = criar_funcao(f, nome="F SoAlfa", liberar_para="setores", setores=[mundo7.A.pk])
    so_b = criar_funcao(f, nome="F SoBeta", liberar_para="setores", setores=[mundo7.B.pk])
    so_base = criar_funcao(f, nome="F SoBase", liberar_para="papeis", papeis=["base"])
    so_coord = criar_funcao(f, nome="F SoCoord", liberar_para="papeis", papeis=["coordenador"])
    esperado = {
        "adm": {"F Todos", "F SoAlfa", "F SoBeta", "F SoBase", "F SoCoord"},
        "bA": {"F Todos", "F SoAlfa", "F SoBase"},
        "bB": {"F Todos", "F SoBeta", "F SoBase"},
        "cA": {"F Todos", "F SoAlfa", "F SoCoord"},
        "bS": {"F Todos", "F SoBase"},
    }
    for k, nomes in esperado.items():
        r = mundo7.c[k].get(reverse("funcoes:catalogo"))
        assert r.status_code == 200 and set(_nomes(r)) == nomes, k
    assert all(x.versao == 1 for x in (todos, so_a, so_b, so_base, so_coord))


def test_inativa_e_rascunho_so_o_adm_ve_com_chips(mundo7, criar_funcao, mk_fluxo7):
    """FUN-02/escopo: inativa e versao 0 invisíveis a não-Adm; Adm vê com chips Rascunho/Inativa."""
    f = mk_fluxo7(mundo7.A)
    criar_funcao(f, nome="F Rascunho", publicar=False)
    criar_funcao(f, nome="F Inativa", ativa=False)
    criar_funcao(f, nome="F Normal")
    assert set(_nomes(mundo7.c["bA"].get(reverse("funcoes:catalogo")))) == {"F Normal"}
    assert set(_nomes(mundo7.c["cA"].get(reverse("funcoes:catalogo")))) == {"F Normal"}
    r = mundo7.c["adm"].get(reverse("funcoes:catalogo"))
    por_nome = {x["nome"]: x for x in r.context["funcoes"]}
    assert set(por_nome) == {"F Rascunho", "F Inativa", "F Normal"}
    assert por_nome["F Rascunho"]["rascunho"] and not por_nome["F Rascunho"]["inativa"]
    assert por_nome["F Inativa"]["inativa"] and not por_nome["F Normal"]["inativa"]
    t = texto(r)
    assert "Rascunho" in t and "Inativa" in t


def test_contexto_do_catalogo_fun13(mundo7, criar_funcao, mk_fluxo7):
    """FUN-13: contexto `funcoes` (dicts com as chaves do contrato), `pode_gerenciar`, `q`."""
    f = mk_fluxo7(mundo7.A)
    criar_funcao(f, nome="F Com Entrada", entradas=[entrada("dia", "data")])
    criar_funcao(f, nome="F Sem Entrada")
    chaves = {"pk", "nome", "descricao", "icone", "rascunho", "inativa", "tem_entradas", "ultima", "url_executar",
              "url_editar", "url_publicar", "url_alternar"}
    r = mundo7.c["adm"].get(reverse("funcoes:catalogo"), {"q": ""})
    assert r.context["pode_gerenciar"] is True and r.context["q"] == ""
    for x in r.context["funcoes"]:
        assert chaves <= set(x), chaves - set(x)
    por = {x["nome"]: x for x in r.context["funcoes"]}
    assert por["F Com Entrada"]["tem_entradas"] is True and por["F Sem Entrada"]["tem_entradas"] is False
    assert por["F Sem Entrada"]["ultima"] is None
    assert mundo7.c["bA"].get(reverse("funcoes:catalogo")).context["pode_gerenciar"] is False


def test_busca_por_nome_e_descricao(mundo7, criar_funcao, mk_fluxo7):
    """FUN-02: ?q= por nome e descrição."""
    f = mk_fluxo7(mundo7.A)
    criar_funcao(f, nome="Relatório mensal", descricao="vendas")
    criar_funcao(f, nome="Outra", descricao="contém ZEBRA no texto")
    r = mundo7.c["bA"].get(reverse("funcoes:catalogo"), {"q": "relat"})
    assert _nomes(r) == ["Relatório mensal"]
    r = mundo7.c["bA"].get(reverse("funcoes:catalogo"), {"q": "zebra"})
    assert _nomes(r) == ["Outra"]


def test_vazio_adm_e_demais(mundo7):
    """FUN-02: mensagens de catálogo vazio."""
    assert "Nenhuma função ainda. Publique um fluxo como função." in texto(mundo7.c["adm"].get(reverse("funcoes:catalogo")))
    assert "Nenhuma função liberada para você ainda." in texto(mundo7.c["bA"].get(reverse("funcoes:catalogo")))


def test_botoes_de_gestao_so_para_adm(mundo7, criar_funcao, mk_fluxo7):
    """FUN-02/permissoes: "Nova função" e menu do cartão só para o Adm; todos veem "Executar"."""
    criar_funcao(mk_fluxo7(mundo7.A), nome="F Botoes")
    h_adm = html(mundo7.c["adm"].get(reverse("funcoes:catalogo")))
    h_base = html(mundo7.c["bA"].get(reverse("funcoes:catalogo")))
    assert "Nova função" in h_adm and "Publicar nova versão" in h_adm
    assert "Nova função" not in h_base and "Publicar nova versão" not in h_base and "Executar" in h_base
    assert reverse("funcoes:nova") not in h_base


def test_ultima_execucao_e_sempre_a_do_proprio_usuario(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """FUN-02/FUN-10: "Sua última execução" só mostra execução do próprio usuário; sem execução → texto padrão."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Ultima")
    r = mundo7.c["bA"].get(reverse("funcoes:catalogo"))
    assert "Você ainda não executou" in texto(r)
    _, e = exec_funcao(mundo7.c["bA2"], fn)
    assert e is not None
    r = mundo7.c["bA"].get(reverse("funcoes:catalogo"))
    assert "Você ainda não executou" in texto(r) and r.context["funcoes"][0]["ultima"] is None
    _, e2 = exec_funcao(mundo7.c["bA"], fn)
    r = mundo7.c["bA"].get(reverse("funcoes:catalogo"))
    ult = r.context["funcoes"][0]["ultima"]
    assert ult["status"] == "sucesso" and ult["url"] == reverse("funcoes:resultado", kwargs={"pk": e2.pk})
    assert "Ver resultado" in texto(r)


def test_catalogo_com_queries_constantes(mundo7, criar_funcao, mk_fluxo7, django_assert_max_num_queries):
    """FUN-02: queries constantes (não crescem com o nº de funções)."""
    f = mk_fluxo7(mundo7.A)
    for i in range(3):
        criar_funcao(f, nome=f"Q{i}")
    c = mundo7.c["bA"]
    with django_assert_max_num_queries(15):
        c.get(reverse("funcoes:catalogo"))
    for i in range(3, 12):
        criar_funcao(f, nome=f"Q{i}")
    with django_assert_max_num_queries(15):
        c.get(reverse("funcoes:catalogo"))


@pytest.mark.parametrize("nome_rota,args", [("funcoes:nova", {}), ("funcoes:editar", "pk"), ("funcoes:publicar", "pk"),
                                            ("funcoes:alternar", "pk")])
def test_gerenciar_negado_a_coordenador_e_base(mundo7, criar_funcao, mk_fluxo7, nome_rota, args):
    """PRM-02/funcoes.gerenciar: Coordenador e Base → 403 (GET e POST); anônimo → 302 login."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Gerencia")
    url = reverse(nome_rota, kwargs={"pk": fn.pk} if args else {})
    for k in ("cA", "bA"):
        assert mundo7.c[k].post(url, {"nome": "x"}).status_code == 403
    for k in ("cA", "bA"):
        if nome_rota in ("funcoes:nova", "funcoes:editar"):
            assert mundo7.c[k].get(url).status_code == 403
    r = mundo7.anon.post(url)
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))
    fn.refresh_from_db()
    assert fn.versao == 1 and fn.ativa is True and fn.nome == "F Gerencia"


def test_alternar_ativa_e_nao_exclui(mundo7, criar_funcao, mk_fluxo7, Funcao):
    """FUN-04: alternar (POST) ativa/desativa; função não é excluída; GET não altera."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Alterna")
    url = reverse("funcoes:alternar", kwargs={"pk": fn.pk})
    r = mundo7.c["adm"].post(url)
    assert r.status_code == 302
    fn.refresh_from_db()
    assert fn.ativa is False
    assert mundo7.c["adm"].get(url).status_code in (405, 302) and Funcao.objects.get(pk=fn.pk).ativa is False
    mundo7.c["adm"].post(url)
    fn.refresh_from_db()
    assert fn.ativa is True and Funcao.objects.count() == 1
