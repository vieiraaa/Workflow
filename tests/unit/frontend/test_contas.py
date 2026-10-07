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


def test_usuario_novo_usa_template_e_erro_por_campo(cliente_adm):
    url = reverse("contas:usuario_novo")
    assert "contas/usuario_novo.html" in nomes(cliente_adm.get(url))
    resposta = cliente_adm.post(url, {"nome": "", "email": ""})
    assert resposta.status_code == 200
    assert "contas/usuario_novo.html" in nomes(resposta)
    assert b"campo__erro" in resposta.content


def test_usuario_editar_usa_template_com_redefinir(cliente_adm, usuario_coordenador):
    resposta = cliente_adm.get(
        reverse("contas:usuario_editar", kwargs={"pk": usuario_coordenador.pk})
    )
    assert "contas/usuario_editar.html" in nomes(resposta)
    redefinir = reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario_coordenador.pk})
    assert redefinir.encode() in resposta.content


def test_usuario_editar_erro_redefinir_senha_rerenderiza(cliente_adm, usuario_coordenador):
    url = reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario_coordenador.pk})
    resposta = cliente_adm.post(url, {"nova_senha": "curta", "confirmacao": "outra"})
    assert resposta.status_code == 200
    assert "contas/usuario_editar.html" in nomes(resposta)
    assert b"campo__erro" in resposta.content


def test_trocar_senha_usa_template_e_erro_por_campo(cliente_base):
    url = reverse("contas:trocar_senha")
    assert "contas/trocar_senha.html" in nomes(cliente_base.get(url))
    resposta = cliente_base.post(url, {"senha_atual": "", "nova_senha": "", "confirmacao": ""})
    assert resposta.status_code == 200
    assert b"campo__erro" in resposta.content


@pytest.mark.parametrize(
    ("rota", "template"),
    [("fluxos:lista", "fluxos/lista.html"), ("execucoes:lista", "execucoes/lista.html")],
)
def test_placeholders_m2_m3(cliente_coordenador, rota, template):
    assert template in nomes(cliente_coordenador.get(reverse(rota)))
