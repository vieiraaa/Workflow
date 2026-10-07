"""Aceite M1: motor de permissão nas rotas do M1. Fontes: PRM-01..08, PAP-02, PAP-03."""
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _rotas(usuario_alvo):
    return {
        "usuarios": reverse("contas:usuarios"),
        "novo": reverse("contas:usuario_novo"),
        "editar": reverse("contas:usuario_editar", kwargs={"pk": usuario_alvo.pk}),
    }


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("nome", ["usuarios", "novo", "editar"])
def test_anonimo_redireciona_para_login_com_next(cliente_anonimo, usuario_base, nome):
    """PRM-01: anônimo em rota de usuários → 302 login?next=<rota>."""
    url = _rotas(usuario_base)[nome]
    r = cliente_anonimo.get(url)
    assert r.status_code == 302
    assert r.url.startswith(reverse("login"))
    assert "next=" in r.url


@pytest.mark.modulo("m1")
def test_anonimo_trocar_senha_redireciona(cliente_anonimo):
    """PRM-01: trocar_senha exige login."""
    r = cliente_anonimo.get(reverse("contas:trocar_senha"))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


@pytest.mark.modulo("m1")
def test_post_anonimo_nao_cria_usuario(cliente_anonimo, dados_usuario):
    """PRM-01: POST anônimo não altera nada."""
    from django.contrib.auth import get_user_model
    antes = get_user_model().objects.count()
    r = cliente_anonimo.post(reverse("contas:usuario_novo"), dados_usuario())
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert get_user_model().objects.count() == antes


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_base"])
@pytest.mark.parametrize("nome", ["usuarios", "novo", "editar"])
def test_sem_acao_usuarios_gerenciar_recebe_403_do_produto(request, usuario_base, cliente, nome):
    """PRM-02: coordenador/base em rotas de usuários → 403 com a tela do produto (link p/ início)."""
    c = request.getfixturevalue(cliente)
    r = c.get(_rotas(usuario_base)[nome])
    assert r.status_code == 403
    html = r.content.decode()
    assert reverse("inicio") in html
    assert "<html" in html.lower()


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_base"])
def test_post_sem_permissao_nao_altera(request, cliente, dados_usuario):
    """PRM-02: POST sem permissão é 403 e não cria usuário."""
    from django.contrib.auth import get_user_model
    c = request.getfixturevalue(cliente)
    antes = get_user_model().objects.count()
    r = c.post(reverse("contas:usuario_novo"), dados_usuario())
    assert r.status_code == 403
    assert get_user_model().objects.count() == antes


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("nome", ["usuarios", "novo", "editar"])
def test_adm_acessa_rotas_de_usuarios(cliente_adm, usuario_base, nome):
    """PRM-02: Adm tem usuarios.gerenciar."""
    assert cliente_adm.get(_rotas(usuario_base)[nome]).status_code == 200


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador", "cliente_base"])
def test_todos_os_papeis_trocam_a_propria_senha(request, cliente):
    """PRM-02/conta.trocar_senha: permitido a todos os papéis."""
    assert request.getfixturevalue(cliente).get(reverse("contas:trocar_senha")).status_code == 200


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador", "cliente_base"])
def test_inicio_redireciona_para_fluxos(request, cliente):
    """PRM-07: inicio → fluxos:lista para papéis com acesso."""
    r = request.getfixturevalue(cliente).get(reverse("inicio"))
    assert r.status_code == 302 and r.url == reverse("fluxos:lista")


@pytest.mark.modulo("m1")
def test_sem_papel_ve_tela_de_sem_acesso(cliente_sem_papel):
    """PRM-07/PAP-02: usuário sem grupo recebe 403 (tela sem acesso) em inicio."""
    r = cliente_sem_papel.get(reverse("inicio"))
    assert r.status_code == 403
    assert "<html" in r.content.decode().lower()


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("nome", ["usuarios", "novo", "editar"])
def test_sem_papel_nao_acessa_usuarios(cliente_sem_papel, usuario_base, nome):
    """PAP-02/PRM-02: sem papel = sem permissão nenhuma."""
    assert cliente_sem_papel.get(_rotas(usuario_base)[nome]).status_code == 403


@pytest.mark.modulo("m1")
def test_sem_papel_trocar_senha_403(cliente_sem_papel):
    """USR-15/PAP-02: sem papel recebe 403 também em trocar_senha."""
    assert cliente_sem_papel.get(reverse("contas:trocar_senha")).status_code == 403


@pytest.mark.modulo("m1")
def test_sem_papel_pode_sair(cliente_sem_papel):
    """USR-15: logout é exceção ao 403 de PAP-02 (POST encerra a sessão)."""
    r = cliente_sem_papel.post(reverse("logout"))
    assert r.status_code == 302
    assert "_auth_user_id" not in cliente_sem_papel.session


@pytest.mark.modulo("m1")
def test_redefinir_senha_exige_login_e_adm(cliente_anonimo, cliente_coordenador, cliente_base, usuario_base):
    """PRM-01/PRM-02/USR-13: redefinir senha só Adm; anônimo → login; demais 403; nada muda."""
    url = reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario_base.pk})
    dados = {"nova_senha": "Invasora-Forte-88", "confirmacao": "Invasora-Forte-88"}
    r = cliente_anonimo.post(url, dados)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert cliente_coordenador.post(url, dados).status_code == 403
    assert cliente_base.post(url, dados).status_code == 403
    usuario_base.refresh_from_db()
    assert not usuario_base.check_password("Invasora-Forte-88")


@pytest.mark.modulo("m1")
def test_redefinir_senha_get_405(cliente_adm, usuario_base):
    """PRM-08/USR-13: rota de redefinir senha é só POST."""
    r = cliente_adm.get(reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario_base.pk}))
    assert r.status_code == 405


@pytest.mark.modulo("m1")
def test_redefinir_senha_sem_csrf_recusada(usuario_adm, usuario_base):
    """PRM-08/SEG-12: redefinir senha exige CSRF."""
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    r = c.post(reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario_base.pk}),
               {"nova_senha": "Invasora-Forte-88", "confirmacao": "Invasora-Forte-88"})
    assert r.status_code == 403
    usuario_base.refresh_from_db()
    assert not usuario_base.check_password("Invasora-Forte-88")


@pytest.mark.modulo("m1")
def test_superuser_sem_grupo_nao_tem_bypass(client, fabrica_usuario):
    """PAP-03: superuser sem grupo não acessa a lista de usuários."""
    u = fabrica_usuario(papel=None)
    u.is_superuser = True
    u.is_staff = True
    u.save()
    client.force_login(u)
    assert client.get(reverse("contas:usuarios")).status_code == 403


@pytest.mark.modulo("m1")
def test_superuser_com_papel_base_segue_o_grupo(client, fabrica_usuario):
    """PAP-03: papel efetivo vem só do grupo."""
    u = fabrica_usuario(papel="Base")
    u.is_superuser = True
    u.save()
    client.force_login(u)
    assert client.get(reverse("contas:usuarios")).status_code == 403


@pytest.mark.modulo("m1")
def test_mutacao_sem_csrf_e_recusada(usuario_adm, dados_usuario):
    """PRM-08: POST sem token CSRF válido é recusado (403) e não cria."""
    from django.contrib.auth import get_user_model
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    antes = get_user_model().objects.count()
    r = c.post(reverse("contas:usuario_novo"), dados_usuario())
    assert r.status_code == 403
    assert get_user_model().objects.count() == antes


@pytest.mark.modulo("m1")
def test_logout_sem_csrf_e_recusado(usuario_adm):
    """PRM-08/SEG-12: logout por POST também exige CSRF."""
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(reverse("logout")).status_code == 403


@pytest.mark.modulo("m1")
def test_menu_adm_tem_usuarios(cliente_adm):
    """PRM-06: sidebar do Adm: Fluxos, Execuções, Usuários."""
    html = cliente_adm.get(reverse("contas:trocar_senha")).content.decode()
    for nome in ("fluxos:lista", "execucoes:lista", "contas:usuarios"):
        assert f'href="{reverse(nome)}"' in html


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_base"])
def test_menu_coordenador_e_base_sem_usuarios(request, cliente):
    """PRM-05/PRM-06: sem 'Usuários' no menu; Fluxos e Execuções presentes."""
    html = request.getfixturevalue(cliente).get(reverse("contas:trocar_senha")).content.decode()
    assert f'href="{reverse("fluxos:lista")}"' in html
    assert f'href="{reverse("execucoes:lista")}"' in html
    assert f'href="{reverse("contas:usuarios")}"' not in html


@pytest.mark.modulo("m1")
def test_mudanca_de_papel_vale_na_proxima_requisicao(client, fabrica_usuario):
    """USR-11/PRM-02: rebaixar Adm→Base tira o acesso sem novo login (sem cache de papel)."""
    u = fabrica_usuario(papel="Adm")
    client.force_login(u)
    assert client.get(reverse("contas:usuarios")).status_code == 200
    u.groups.set([Group.objects.get(name="Base")])
    assert client.get(reverse("contas:usuarios")).status_code == 403
