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
    }


def test_shell_com_rotas_ainda_inexistentes_omite_itens(usuario_adm):
    dados = contexto.shell(_request(usuario_adm))
    assert dados["usuario_nome"] == "Ana Admin"
    assert dados["usuario_papel"] == "Administrador"
    assert dados["menu"] == []  # fluxos/execuções/usuários chegam nos módulos seguintes


def test_menu_por_papel(monkeypatch, usuario_adm, usuario_coordenador, usuario_base):
    monkeypatch.setattr(contexto, "reverse", lambda rota: f"/{rota}/")
    chaves = lambda u: [i["chave"] for i in contexto.montar_menu(_request(u))]  # noqa: E731
    assert chaves(usuario_adm) == ["fluxos", "execucoes", "usuarios"]
    assert chaves(usuario_coordenador) == ["fluxos", "execucoes"]
    assert chaves(usuario_base) == ["fluxos", "execucoes"]


def test_item_ativo_pelo_namespace(monkeypatch, usuario_adm):
    monkeypatch.setattr(contexto, "reverse", lambda rota: f"/{rota}/")
    request = _request(usuario_adm)
    request.resolver_match = type("R", (), {"namespace": "fluxos"})()
    ativos = {i["chave"]: i["ativo"] for i in contexto.montar_menu(request)}
    assert ativos == {"fluxos": True, "execucoes": False, "usuarios": False}


def test_pagina_renderiza_shell(cliente_adm):
    assert reverse("inicio")
    resposta = cliente_adm.get("/nao-existe/")
    assert resposta.context["usuario_papel"] == "Administrador"
