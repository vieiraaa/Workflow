"""Contexto da lista de usuários, sem depender do template (resposta não renderizada)."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.contas.views_usuarios import UsuarioListaView
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]


def _contexto(usuario, **params):
    request = RequestFactory().get("/usuarios/", params)
    request.user = usuario
    return UsuarioListaView.as_view()(request).context_data


def _emails(contexto):
    return [linha["email"] for linha in contexto["usuarios"]]


def test_anonimo_vai_para_login_e_sem_papel_recebe_403(usuario_sem_papel, usuario_base):
    request = RequestFactory().get("/usuarios/")
    request.user = AnonymousUser()
    assert UsuarioListaView.as_view()(request).status_code == 302
    for usuario in (usuario_sem_papel, usuario_base):
        with pytest.raises(PermissionDenied):
            _contexto(usuario)


def test_linhas_trazem_papel_e_status(usuario_adm):
    criar_usuario("i@exemplo.test", "Inativo", "Base", is_active=False)
    linhas = {linha["email"]: linha for linha in _contexto(usuario_adm)["usuarios"]}
    assert linhas["adm@exemplo.test"]["papel_id"] == "adm"
    assert linhas["adm@exemplo.test"]["papel_rotulo"] == "Administrador"
    assert linhas["i@exemplo.test"]["ativo"] is False
    assert linhas["i@exemplo.test"]["papel_rotulo"] == "Usuário base"


def test_usuario_sem_papel_aparece_como_sem_papel(usuario_adm, usuario_sem_papel):
    linha = next(x for x in _contexto(usuario_adm)["usuarios"] if x["pk"] == usuario_sem_papel.pk)
    assert linha["papel_id"] == ""
    assert linha["papel_rotulo"] == "Sem papel"


def test_filtros_e_busca(usuario_adm, usuario_base, usuario_coordenador):
    assert _emails(_contexto(usuario_adm, papel="base")) == [usuario_base.email]
    assert _emails(_contexto(usuario_adm, q="COORD")) == [usuario_coordenador.email]
    assert _emails(_contexto(usuario_adm, papel="base", ativo="0")) == []


def test_valores_invalidos_sao_ignorados(usuario_adm):
    contexto = _contexto(usuario_adm, papel="root", ativo="x", ordem="senha", pagina="abc")
    assert contexto["papel_atual"] == ""
    assert contexto["ativo_atual"] == ""
    assert contexto["ordem"] == "nome"
    assert contexto["page_obj"].number == 1


def test_ordenacao_desc_e_links_de_cabecalho(usuario_adm, usuario_base):
    contexto = _contexto(usuario_adm, ordem="-nome")
    assert _emails(contexto)[0] == usuario_base.email  # "Bia" > "Ana"
    assert contexto["ordenacoes"]["nome"]["sentido"] == "desc"
    assert contexto["ordenacoes"]["nome"]["url"] == "?"  # volta ao padrão (asc)
    assert contexto["ordenacoes"]["email"]["url"] == "?ordem=email"


def test_paginacao_ultima_pagina_e_consulta(usuario_adm):
    for i in range(30):
        criar_usuario(f"p{i:02d}@exemplo.test", f"Pessoa {i:02d}")
    contexto = _contexto(usuario_adm, q="p", pagina="99", ordem="email")
    assert contexto["page_obj"].number == 2
    assert contexto["consulta"] == "q=p&ordem=email&"
    assert _contexto(usuario_adm, q="p")["page_obj"].paginator.per_page == 25
    assert _contexto(usuario_adm, pagina="-3")["page_obj"].number == 1


def test_filtros_segmentados_marcam_o_ativo(usuario_adm):
    contexto = _contexto(usuario_adm, papel="coordenador", ativo="1")
    assert [o["rotulo"] for o in contexto["filtros_papel"]] == [
        "Todos",
        "Administrador",
        "Coordenador",
        "Usuário base",
    ]
    assert [o["rotulo"] for o in contexto["filtros_papel"] if o["ativo"]] == ["Coordenador"]
    assert [o["rotulo"] for o in contexto["filtros_status"] if o["ativo"]] == ["Ativos"]


def test_queries_constantes(usuario_adm, django_assert_max_num_queries):
    _contexto(usuario_adm)
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as base:
        _contexto(usuario_adm)
    for i in range(30):
        criar_usuario(f"q{i:02d}@exemplo.test", f"Pessoa {i:02d}")
    with django_assert_max_num_queries(len(base.captured_queries)):
        _contexto(usuario_adm)
