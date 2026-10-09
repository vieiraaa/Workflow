"""Aceite M1: login/logout. Fontes: PAP-04, SEG-15, PRM-01, PRM-07 (TEL-01)."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.mark.modulo("m1")
def test_login_get_anonimo_ok_sem_shell():
    """PRM-01/TEL-01: a rota login é pública."""
    from django.test import Client
    r = Client().get(reverse("login"))
    assert r.status_code == 200


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("papel", ["Adm", "Coordenador", "Base"])
def test_login_valido_entra_e_inicio_e_a_home(client, fabrica_usuario, papel, senha_padrao):
    """PRM-07 (revisado no M4, HOM-01): login válido entra na sessão; `inicio` é a Home (200), sem redirect."""
    u = fabrica_usuario(papel=papel)
    r = client.post(reverse("login"), {"username": u.email, "password": senha_padrao})
    assert r.status_code == 302
    assert "_auth_user_id" in client.session
    r2 = client.get(reverse("inicio"))
    assert r2.status_code == 200


@pytest.mark.modulo("m1")
def test_login_email_inexistente_e_senha_errada_mesma_mensagem(client, fabrica_usuario):
    """SEG-15: mensagem genérica, igual para e-mail inexistente e senha errada."""
    u = fabrica_usuario()
    r1 = client.post(reverse("login"), {"username": u.email, "password": "errada-errada-123"})
    r2 = client.post(reverse("login"), {"username": "naoexiste@exemplo.test", "password": "errada-errada-123"})
    for r in (r1, r2):
        assert r.status_code == 200
        assert "E-mail ou senha inválidos." in r.content.decode()
        assert "_auth_user_id" not in client.session


@pytest.mark.modulo("m1")
def test_login_inativo_nao_entra(client, fabrica_usuario, senha_padrao):
    """PAP-04: usuário inativo não consegue logar."""
    u = fabrica_usuario(ativo=False)
    r = client.post(reverse("login"), {"username": u.email, "password": senha_padrao})
    assert r.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.modulo("m1")
def test_sessao_de_quem_foi_desativado_encerra_na_proxima_requisicao(client, fabrica_usuario):
    """PAP-04: desativar com sessão aberta encerra a sessão na próxima requisição."""
    u = fabrica_usuario(papel="Coordenador")
    client.force_login(u)
    assert client.get(reverse("contas:trocar_senha")).status_code == 200
    u.is_active = False
    u.save()
    r = client.get(reverse("contas:trocar_senha"))
    assert r.status_code == 302
    assert reverse("login") in r.url


@pytest.mark.modulo("m1")
def test_logout_so_por_post(cliente_base):
    """SEG-15/USR-13: GET em logout → 405 e não encerra a sessão; POST encerra."""
    r = cliente_base.get(reverse("logout"))
    assert r.status_code == 405
    assert "_auth_user_id" in cliente_base.session
    r = cliente_base.post(reverse("logout"))
    assert r.status_code == 302
    assert "_auth_user_id" not in cliente_base.session


@pytest.mark.modulo("m1")
def test_logout_anonimo_nao_quebra(cliente_anonimo):
    """SEG-15/PRM-01: POST em logout sem sessão nunca dá 500."""
    r = cliente_anonimo.post(reverse("logout"))
    assert r.status_code < 500


@pytest.mark.modulo("m1")
def test_anonimo_em_inicio_vai_para_login_com_next(cliente_anonimo):
    """PRM-01: anônimo em rota protegida → 302 para login com ?next=."""
    r = cliente_anonimo.get(reverse("inicio"))
    assert r.status_code == 302
    assert r.url.startswith(reverse("login"))
    assert "next=" in r.url
