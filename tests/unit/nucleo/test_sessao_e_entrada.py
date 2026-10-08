import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from apps.contas.sessoes import encerrar_sessoes
from apps.nucleo.entrada import limpar_texto

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]


def test_limpar_texto():
    assert limpar_texto("  a\x00b  ") == "ab"
    assert limpar_texto(None) == ""
    assert len(limpar_texto("x" * 1000)) == 200


def test_busca_com_nul_nao_quebra(cliente_adm):
    assert cliente_adm.get(reverse("contas:usuarios"), {"q": "\x00"}).status_code == 200


def test_sessao_de_inativo_e_apagada_e_reativar_nao_ressuscita(usuario_adm):
    cliente = Client()
    cliente.force_login(usuario_adm)
    usuario_adm.is_active = False
    usuario_adm.save()
    assert cliente.get(reverse("contas:trocar_senha")).status_code == 302
    assert "_auth_user_id" not in cliente.session
    usuario_adm.is_active = True
    usuario_adm.save()
    assert cliente.get(reverse("contas:trocar_senha")).status_code == 302


def test_encerrar_sessoes_so_do_usuario(usuario_adm, usuario_base):
    for usuario in (usuario_adm, usuario_base):
        Client().force_login(usuario)
    encerrar_sessoes(usuario_base)
    restantes = [s.get_decoded().get("_auth_user_id") for s in Session.objects.all()]
    assert restantes == [str(usuario_adm.pk)]


def test_desativar_pela_edicao_encerra_sessoes_do_alvo(cliente_adm, usuario_coordenador):
    alvo = Client()
    alvo.force_login(usuario_coordenador)
    cliente_adm.post(
        reverse("contas:usuario_editar", kwargs={"pk": usuario_coordenador.pk}),
        {
            "nome": usuario_coordenador.nome,
            "email": usuario_coordenador.email,
            "papel": "coordenador",
        },
    )
    assert not Session.objects.filter(pk=alvo.session.session_key).exists()
