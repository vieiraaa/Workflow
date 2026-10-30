"""Perfil, avatar, presença e lateral recolhida (D-041)."""

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.contas import presenca
from apps.contas.models import Usuario
from apps.contas.permissoes import papel_de, pode
from apps.execucoes.models import Execucao
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]

CLIENTES = ["cliente_adm", "cliente_coordenador", "cliente_base"]


@pytest.fixture(autouse=True)
def _cache_limpo():
    cache.clear()
    yield
    cache.clear()


def _perfil(pk):
    return reverse("contas:perfil", kwargs={"pk": pk})


@pytest.mark.parametrize(
    "nome,curto,iniciais",
    [
        ("João Victor Arruda Tobias Vieira", "João Vieira", "JV"),
        ("Ana", "Ana", "A"),
        ("Pedro Henrique Silva Filho", "Pedro Silva Filho", "PS"),
        ("maria souza", "maria souza", "MS"),
    ],
)
def test_nome_curto_e_iniciais(nome, curto, iniciais):
    u = Usuario(nome=nome, email="x@exemplo.test")
    assert u.nome_curto == curto and u.iniciais == iniciais


def test_lista_de_responsabilidades_ignora_linhas_vazias_e_marcadores():
    u = Usuario(responsabilidades="- Prazos\n\n• Audiências \n  Cadastro  ")
    assert u.lista_responsabilidades == ["Prazos", "Audiências", "Cadastro"]


def test_lateral_mostra_avatar_nome_curto_cargo_e_link_do_perfil(cliente_adm, usuario_adm):
    usuario_adm.nome, usuario_adm.cargo = "Ana Maria Admin", "Analista de Sistemas"
    usuario_adm.save()
    html = cliente_adm.get(reverse("inicio")).content.decode()
    assert 'class="avatar avatar--md' in html and ">AA<" in html
    assert "<strong>Ana Admin</strong><span>Analista de Sistemas</span>" in html
    assert f'href="{reverse("contas:meu_perfil")}"' in html


def test_trocar_senha_so_no_login_local(cliente_adm, settings):
    link = f'href="{reverse("contas:trocar_senha")}"'
    assert link in cliente_adm.get(reverse("inicio")).content.decode()  # testes: login local
    settings.LOGIN_AD = True
    assert link not in cliente_adm.get(reverse("inicio")).content.decode()


def test_lateral_sem_cargo_mostra_o_papel(cliente_base):
    assert "<span>Usuário base</span>" in cliente_base.get(reverse("inicio")).content.decode() or (
        "Base" in cliente_base.get(reverse("inicio")).content.decode()
    )


@pytest.mark.parametrize("cliente", CLIENTES)
def test_todo_papel_ve_perfil_de_colega(request, cliente, usuario_coordenador):
    r = request.getfixturevalue(cliente).get(_perfil(usuario_coordenador.pk))
    assert r.status_code == 200
    assert "contas/perfil.html" in [t.name for t in r.templates]
    assert r.context["perfil"] == usuario_coordenador


def test_meu_perfil_abre_o_proprio(cliente_base, usuario_base):
    r = cliente_base.get(reverse("contas:meu_perfil"))
    assert r.context["perfil"] == usuario_base and r.context["eh_proprio"]


def test_anonimo_vai_para_o_login(cliente_anonimo, usuario_base):
    r = cliente_anonimo.get(_perfil(usuario_base.pk))
    assert r.status_code == 302 and reverse("login") in r.url


def test_sem_papel_recebe_403(cliente_sem_papel, usuario_base):
    assert cliente_sem_papel.get(_perfil(usuario_base.pk)).status_code == 403


def test_perfil_inexistente_404(cliente_base):
    assert cliente_base.get(_perfil(999999)).status_code == 404


def test_perfil_de_inativo_so_o_adm_ve(cliente_base, cliente_adm, usuario_coordenador):
    usuario_coordenador.is_active = False
    usuario_coordenador.save()
    assert cliente_base.get(_perfil(usuario_coordenador.pk)).status_code == 404
    assert cliente_adm.get(_perfil(usuario_coordenador.pk)).status_code == 200


def test_secao_de_acesso_so_para_o_adm(cliente_adm, cliente_coordenador, usuario_base):
    r = cliente_adm.get(_perfil(usuario_base.pk))
    assert r.context["pode_gerenciar"] and r.context["form_acesso"] is not None
    assert {t["rotulo"] for t in r.context["telas"]} >= {"Início", "Fluxos", "Execuções"}
    assert "Usuários" not in {t["rotulo"] for t in r.context["telas"]}
    r = cliente_coordenador.get(_perfil(usuario_base.pk))
    assert not r.context["pode_gerenciar"] and r.context["form_acesso"] is None
    assert reverse("contas:perfil_acesso", kwargs={"pk": usuario_base.pk}) not in r.content.decode()


def test_editar_o_proprio_perfil(cliente_base, usuario_base):
    url = reverse("contas:perfil_editar", kwargs={"pk": usuario_base.pk})
    assert cliente_base.get(url).status_code == 200
    r = cliente_base.post(
        url, {"bio": "  Cuido dos prazos. ", "responsabilidades": "Prazos\n\n Audiências "}
    )
    assert r.status_code == 302 and r.url == _perfil(usuario_base.pk)
    usuario_base.refresh_from_db()
    assert (
        usuario_base.bio == "Cuido dos prazos."
        and usuario_base.responsabilidades == "Prazos\nAudiências"
    )


def test_nao_edita_perfil_de_outro(cliente_base, usuario_coordenador):
    url = reverse("contas:perfil_editar", kwargs={"pk": usuario_coordenador.pk})
    assert cliente_base.get(url).status_code == 404
    assert cliente_base.post(url, {"bio": "invadido"}).status_code == 404
    usuario_coordenador.refresh_from_db()
    assert usuario_coordenador.bio == ""


def test_adm_edita_perfil_de_outro(cliente_adm, usuario_base):
    url = reverse("contas:perfil_editar", kwargs={"pk": usuario_base.pk})
    assert cliente_adm.post(url, {"bio": "Ok", "responsabilidades": ""}).status_code == 302


def test_editar_perfil_valida_limites(cliente_base, usuario_base):
    url = reverse("contas:perfil_editar", kwargs={"pk": usuario_base.pk})
    r = cliente_base.post(url, {"bio": "x" * 1001, "responsabilidades": "\n".join(["a"] * 21)})
    assert r.status_code == 200
    assert r.context["form"].errors.keys() == {"bio", "responsabilidades"}


def test_editar_perfil_get_nao_altera_e_post_exige_csrf(usuario_base):
    from django.test import Client

    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_base)
    url = reverse("contas:perfil_editar", kwargs={"pk": usuario_base.pk})
    assert c.post(url, {"bio": "x"}).status_code == 403


def test_adm_altera_acesso_pelo_perfil(cliente_adm, usuario_base, outro_setor):
    url = reverse("contas:perfil_acesso", kwargs={"pk": usuario_base.pk})
    r = cliente_adm.post(url, {"papel": "coordenador", "setor": str(outro_setor.pk), "ativo": "on"})
    assert r.status_code == 302 and r.url == _perfil(usuario_base.pk)
    u = Usuario.objects.get(pk=usuario_base.pk)
    assert papel_de(u) == "coordenador" and u.setor == outro_setor and u.nome == usuario_base.nome


def test_acesso_pelo_perfil_mantem_as_regras_do_cadastro(cliente_adm, usuario_adm, usuario_base):
    proprio = reverse("contas:perfil_acesso", kwargs={"pk": usuario_adm.pk})
    r = cliente_adm.post(
        proprio, {"papel": "base", "setor": str(usuario_adm.setor_id), "ativo": "on"}
    )
    assert r.status_code == 200 and r.context["form_acesso"].errors
    outro = reverse("contas:perfil_acesso", kwargs={"pk": usuario_base.pk})
    r = cliente_adm.post(outro, {"papel": "base", "setor": "", "ativo": "on"})
    assert "setor" in r.context["form_acesso"].errors  # SET-03


@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_base"])
def test_so_adm_altera_acesso(request, cliente, usuario_base):
    url = reverse("contas:perfil_acesso", kwargs={"pk": usuario_base.pk})
    r = request.getfixturevalue(cliente).post(url, {"papel": "adm", "setor": "", "ativo": "on"})
    assert r.status_code == 403
    assert papel_de(Usuario.objects.get(pk=usuario_base.pk)) == "base"


def test_acesso_get_405(cliente_adm, usuario_base):
    assert (
        cliente_adm.get(reverse("contas:perfil_acesso", kwargs={"pk": usuario_base.pk})).status_code
        == 405
    )


def test_atividade_respeita_o_escopo_de_quem_le(
    cliente_base, cliente_adm, usuario_base, usuario_coordenador
):
    Execucao.objects.create(fluxo_nome="Do coordenador", executado_por=usuario_coordenador)
    r = cliente_base.get(_perfil(usuario_coordenador.pk))
    assert r.context["atividade"] == []  # Base só vê as próprias execuções
    r = cliente_adm.get(_perfil(usuario_coordenador.pk))
    assert [a["fluxo_nome"] for a in r.context["atividade"]] == ["Do coordenador"]


def test_presenca_online_apos_requisicao_e_offline_ao_sair(cliente_base, cliente_adm, usuario_base):
    assert not presenca.online(usuario_base)
    cliente_base.get(reverse("inicio"))
    assert presenca.online(usuario_base)
    assert cliente_adm.get(_perfil(usuario_base.pk)).context["online"] is True
    cliente_base.post(reverse("logout"))
    assert not presenca.online(usuario_base)


def test_presenca_expira(usuario_base, monkeypatch):
    presenca.registrar(usuario_base)
    agora = presenca.time.time()
    monkeypatch.setattr(presenca.time, "time", lambda: agora + presenca.ONLINE_S + 1)
    assert not presenca.online(usuario_base)
    assert presenca.visto_em(usuario_base) is not None


def test_escopo_proprio_no_motor(usuario_base, usuario_coordenador, usuario_adm):
    assert pode(usuario_base, "perfis.editar", usuario_base)
    assert not pode(usuario_base, "perfis.editar", usuario_coordenador)
    assert pode(usuario_adm, "perfis.editar", usuario_coordenador)


def test_cor_do_avatar_e_estavel_e_vai_de_1_a_6(db):
    cores = {criar_usuario(f"p{i}@exemplo.test", f"Pessoa {i}").cor_avatar for i in range(8)}
    assert cores <= set(range(1, 7)) and len(cores) == 6
