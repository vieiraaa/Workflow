"""Render das telas de usuários (M1)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.modulo("m1")


def nomes(resposta):
    return [t.name for t in resposta.templates]


def test_lista_usuarios_usa_template(cliente_adm):
    resposta = cliente_adm.get(reverse("contas:usuarios"))
    assert resposta.status_code == 200
    assert "contas/usuarios.html" in nomes(resposta)


def test_lista_escapa_nome(cliente_adm, usuario_base):
    usuario_base.nome = "<script>alert(1)</script>"
    usuario_base.save()
    conteudo = cliente_adm.get(reverse("contas:usuarios")).content.decode()
    assert "<script>alert(1)</script>" not in conteudo
    assert "&lt;script&gt;" in conteudo


def test_lista_vazio_busca(cliente_adm):
    resposta = cliente_adm.get(reverse("contas:usuarios"), {"q": "zzz-inexistente"})
    assert "Nenhum usuário encontrado".encode() in resposta.content
