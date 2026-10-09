import pytest
from django.urls import reverse

pytestmark = [pytest.mark.modulo("m0"), pytest.mark.django_db]

CLIENTES = ["cliente_adm", "cliente_coordenador", "cliente_base"]


def test_login_get_anonimo_200(cliente_anonimo):
    resposta = cliente_anonimo.get(reverse("login"))
    assert resposta.status_code == 200
    assert "form" in resposta.context


@pytest.mark.parametrize("email", ["adm@exemplo.test", "coord@exemplo.test", "base@exemplo.test"])
def test_login_com_cada_papel(request, cliente_anonimo, senha_teste, email):
    papel = {"adm@exemplo.test": "usuario_adm", "coord@exemplo.test": "usuario_coordenador"}.get(
        email, "usuario_base"
    )
    request.getfixturevalue(papel)
    resposta = cliente_anonimo.post(
        reverse("login"), {"username": email.upper(), "password": senha_teste}
    )
    assert resposta.status_code == 302
    assert resposta.url == reverse("inicio")
    assert "_auth_user_id" in cliente_anonimo.session


def test_login_senha_errada_mensagem_generica(cliente_anonimo, usuario_adm):
    resposta = cliente_anonimo.post(
        reverse("login"), {"username": usuario_adm.email, "password": "errada"}
    )
    assert resposta.status_code == 200
    assert list(resposta.context["form"].non_field_errors()) == ["E-mail ou senha inválidos."]


def test_login_email_inexistente_mesma_mensagem(cliente_anonimo, usuario_adm):
    erros = []
    for email in (usuario_adm.email, "naoexiste@exemplo.test"):
        resposta = cliente_anonimo.post(reverse("login"), {"username": email, "password": "x"})
        erros.append(list(resposta.context["form"].non_field_errors()))
    assert erros[0] == erros[1] == ["E-mail ou senha inválidos."]


def test_usuario_inativo_nao_loga_e_sessao_cai(
    usuario_adm, cliente_adm, cliente_anonimo, senha_teste
):
    usuario_adm.is_active = False
    usuario_adm.save()
    resposta = cliente_anonimo.post(
        reverse("login"), {"username": usuario_adm.email, "password": senha_teste}
    )
    assert resposta.status_code == 200
    assert cliente_adm.get(reverse("inicio")).status_code == 302  # sessão aberta encerrada


def test_inicio_exige_login(cliente_anonimo):
    resposta = cliente_anonimo.get(reverse("inicio"))
    assert resposta.status_code == 302
    assert resposta.url == f"{reverse('login')}?next={reverse('inicio')}"


@pytest.mark.parametrize("cliente", CLIENTES)
def test_inicio_logado_com_papel_e_a_home(request, cliente):
    """PRM-07 revisado (M4): `inicio` é a Home, sem redirect."""
    resposta = request.getfixturevalue(cliente).get(reverse("inicio"))
    assert resposta.status_code == 200
    assert "inicio/inicio.html" in [t.name for t in resposta.templates]


def test_inicio_sem_papel_403_do_produto(cliente_sem_papel):
    resposta = cliente_sem_papel.get(reverse("inicio"))
    assert resposta.status_code == 403
    assert "erros/403.html" in [t.name for t in resposta.templates]


def test_logout_so_por_post(cliente_adm):
    assert cliente_adm.get(reverse("logout")).status_code == 405
    assert "_auth_user_id" in cliente_adm.session


@pytest.mark.parametrize("cliente", CLIENTES)
def test_logout_post_encerra_sessao(request, cliente):
    cliente = request.getfixturevalue(cliente)
    resposta = cliente.post(reverse("logout"))
    assert resposta.status_code == 302
    assert resposta.url == reverse("login")
    assert "_auth_user_id" not in cliente.session


def test_logout_anonimo_nao_quebra(cliente_anonimo):
    assert cliente_anonimo.post(reverse("logout")).status_code == 302


def test_logout_exige_csrf():
    from django.test import Client

    cliente = Client(enforce_csrf_checks=True)
    assert cliente.post(reverse("logout")).status_code == 403


def test_rota_inexistente_404_do_produto(cliente_coordenador):
    resposta = cliente_coordenador.get("/nao-existe/")
    assert resposta.status_code == 404
    assert "erros/404.html" in [t.name for t in resposta.templates]
