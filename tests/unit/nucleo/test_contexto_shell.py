import pytest
from django.test import RequestFactory
from django.urls import reverse

from apps.nucleo import contexto

pytestmark = [pytest.mark.modulo("m0"), pytest.mark.django_db]


def _request(usuario):
    request = RequestFactory().get("/")
    request.user = usuario
    return request


def test_shell_anonimo():
    from django.contrib.auth.models import AnonymousUser

    assert contexto.shell(_request(AnonymousUser())) == {
        "menu": [],
        "usuario_nome": "",
        "usuario_papel": "",
        "sem_papel": False,
    }


def test_shell_do_adm(usuario_adm):
    dados = contexto.shell(_request(usuario_adm))
    assert dados["usuario_nome"] == "Ana Admin"
    assert dados["usuario_papel"] == "Administrador"
    assert dados["sem_papel"] is False
    assert [i["chave"] for i in dados["menu"]] == [
        "inicio",
        "funcoes",
        "fluxos",
        "execucoes",
        "usuarios",
        "setores",
        "credenciais",
        "juridico",
    ]


def test_shell_sem_papel(usuario_sem_papel):
    dados = contexto.shell(_request(usuario_sem_papel))
    assert dados["sem_papel"] is True
    assert dados["menu"] == []


def test_shell_omite_itens_de_rotas_inexistentes(monkeypatch, usuario_adm):
    def reverse_parcial(rota):
        if rota == "contas:usuarios":
            return "/usuarios/"
        raise contexto.NoReverseMatch(rota)

    monkeypatch.setattr(contexto, "reverse", reverse_parcial)
    assert [i["chave"] for i in contexto.montar_menu(_request(usuario_adm))] == ["usuarios"]


def test_menu_por_papel(monkeypatch, usuario_adm, usuario_coordenador, usuario_base):
    monkeypatch.setattr(contexto, "reverse", lambda rota: f"/{rota}/")
    chaves = lambda u: [i["chave"] for i in contexto.montar_menu(_request(u))]  # noqa: E731
    assert chaves(usuario_adm) == [
        "inicio",
        "funcoes",
        "fluxos",
        "execucoes",
        "usuarios",
        "setores",
        "credenciais",
        "juridico",
    ]
    assert chaves(usuario_coordenador) == ["inicio", "funcoes", "fluxos", "execucoes"]
    assert chaves(usuario_base) == ["inicio", "funcoes", "fluxos", "execucoes"]


def test_item_ativo_pelo_namespace(monkeypatch, usuario_adm):
    monkeypatch.setattr(contexto, "reverse", lambda rota: f"/{rota}/")
    request = _request(usuario_adm)
    request.resolver_match = type("R", (), {"namespace": "fluxos"})()
    ativos = {i["chave"]: i["ativo"] for i in contexto.montar_menu(request)}
    assert ativos == {
        "inicio": False,
        "funcoes": False,
        "fluxos": True,
        "execucoes": False,
        "usuarios": False,
        "setores": False,
        "credenciais": False,
        "juridico": False,
    }


def test_pagina_renderiza_shell(cliente_adm):
    assert reverse("inicio")
    resposta = cliente_adm.get("/nao-existe/")
    assert resposta.context["usuario_papel"] == "Administrador"


def test_item_do_juridico_traz_o_grupo_e_so_aparece_com_acesso(
    monkeypatch, usuario_adm, usuario_coordenador
):
    monkeypatch.setattr(contexto, "reverse", lambda rota: f"/{rota}/")
    menu = {i["chave"]: i for i in contexto.montar_menu(_request(usuario_adm))}
    assert menu["juridico"]["grupo"] == "Jurídico" and menu["juridico"]["icone"] == "scale"
    assert menu["inicio"]["grupo"] == ""
    # coordenador sem setor na lista de acesso: o menu não mostra o Jurídico (CAD-02)
    assert "juridico" not in {
        i["chave"] for i in contexto.montar_menu(_request(usuario_coordenador))
    }
