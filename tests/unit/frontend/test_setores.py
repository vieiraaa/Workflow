"""Render das telas de setores (TEL-14/15) e do campo setor nos formulários (SET-02/03/04)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.modulo("m4")


def nomes(resposta):
    return [t.name for t in resposta.templates]


def test_setores_lista_usa_template_e_menu(cliente_adm):
    resposta = cliente_adm.get(reverse("contas:setores"))
    assert resposta.status_code == 200
    assert "contas/setores.html" in nomes(resposta)
    assert b"Geral" in resposta.content and b"Novo setor" in resposta.content
    assert reverse("contas:setores").encode() in resposta.content  # item do menu


def test_setores_lista_escapa_nome(cliente_adm):
    from apps.contas.models import Setor

    Setor.objects.create(nome="<script>x</script>")
    resposta = cliente_adm.get(reverse("contas:setores"))
    assert b"<script>x</script>" not in resposta.content
    assert b"&lt;script&gt;x&lt;/script&gt;" in resposta.content


def test_setor_novo_usa_template_e_erro_por_campo(cliente_adm):
    resposta = cliente_adm.get(reverse("contas:setor_novo"))
    assert "contas/setor_novo.html" in nomes(resposta)
    assert b'name="nome"' in resposta.content and b'name="ativo"' in resposta.content
    resposta = cliente_adm.post(reverse("contas:setor_novo"), {"nome": "geral", "ativo": "on"})
    assert resposta.status_code == 200
    assert "Já existe um setor com este nome.".encode() in resposta.content


def test_setor_editar_usa_template(cliente_adm):
    from apps.contas.models import Setor

    setor = Setor.objects.first()
    resposta = cliente_adm.get(reverse("contas:setor_editar", kwargs={"pk": setor.pk}))
    assert "contas/setor_editar.html" in nomes(resposta)
    assert setor.nome.encode() in resposta.content


def test_formulario_usuario_tem_select_de_setor(cliente_adm):
    resposta = cliente_adm.get(reverse("contas:usuario_novo"))
    assert b'name="setor"' in resposta.content


def test_lista_usuarios_tem_coluna_e_filtro_de_setor(cliente_adm):
    resposta = cliente_adm.get(reverse("contas:usuarios"))
    assert b">Setor<" in resposta.content and b'aria-label="Setor"' in resposta.content


def test_modal_do_fluxo_tem_select_de_setor_so_para_adm(cliente_adm, cliente_coordenador):
    assert b'name="setor"' in cliente_adm.get(reverse("fluxos:lista")).content
    assert b'name="setor"' not in cliente_coordenador.get(reverse("fluxos:lista")).content
