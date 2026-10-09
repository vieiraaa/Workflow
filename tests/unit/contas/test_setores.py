import pytest
from django.urls import reverse

from apps.contas.forms_setores import SetorForm
from apps.fluxos import demo
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m4"), pytest.mark.django_db]


def test_form_nome_unico_sem_diferenciar_caixa(setor_geral):
    form = SetorForm({"nome": " geral ", "ativo": "on"})
    assert not form.is_valid()
    assert form.errors["nome"] == ["Já existe um setor com este nome."]


def test_form_editar_mantendo_nome_e_desativar(setor_geral):
    form = SetorForm({"nome": "Geral"}, instance=setor_geral)
    assert form.is_valid()
    form.salvar()
    setor_geral.refresh_from_db()
    assert setor_geral.ativo is False


def test_setores_so_adm(cliente_coordenador, cliente_base, cliente_anonimo, cliente_adm):
    url = reverse("contas:setores")
    assert cliente_coordenador.get(url).status_code == 403
    assert cliente_base.get(url).status_code == 403
    assert cliente_anonimo.get(url).status_code == 302
    contexto = cliente_adm.get(url).context
    assert contexto["total"] == len(contexto["setores"]) >= 1
    assert contexto["url_novo"] == reverse("contas:setor_novo")


def test_editar_setor_pelo_post_e_toast(cliente_adm, outro_setor):
    r = cliente_adm.post(
        reverse("contas:setor_editar", kwargs={"pk": outro_setor.pk}),
        {"nome": "Fin", "ativo": "on"},
    )
    assert r.status_code == 302
    outro_setor.refresh_from_db()
    assert outro_setor.nome == "Fin"


def test_usuario_nao_adm_exige_setor_ativo(cliente_adm, outro_setor):
    outro_setor.ativo = False
    outro_setor.save()
    dados = {"nome": "N", "email": "n@exemplo.test", "papel": "base"}
    dados |= {"senha": "Senha-Forte-Ficticia-91", "confirmacao": "Senha-Forte-Ficticia-91"}
    r = cliente_adm.post(reverse("contas:usuario_novo"), {**dados, "setor": outro_setor.pk})
    assert r.status_code == 200
    assert r.context["form"].errors["setor"] == ["Setor inválido."]


def test_editar_mantem_setor_inativo_ja_vinculado(cliente_adm, outro_setor):
    base = criar_usuario("b2@exemplo.test", "B2", "Base", setor=outro_setor)
    outro_setor.ativo = False
    outro_setor.save()
    r = cliente_adm.post(
        reverse("contas:usuario_editar", kwargs={"pk": base.pk}),
        {
            "nome": "B2",
            "email": base.email,
            "papel": "base",
            "ativo": "on",
            "setor": outro_setor.pk,
        },
    )
    assert r.status_code == 302


def test_lista_usuarios_filtro_setor(
    cliente_adm, outro_setor, usuario_base, django_assert_num_queries
):
    criar_usuario("f@exemplo.test", "Fin", "Base", setor=outro_setor)
    r = cliente_adm.get(reverse("contas:usuarios"), {"setor": outro_setor.pk})
    assert [u["email"] for u in r.context["usuarios"]] == ["f@exemplo.test"]
    assert r.context["usuarios"][0]["setor_nome"] == "Financeiro"
    assert any(f["ativo"] for f in r.context["filtros_setor"][1:])
    assert cliente_adm.get(reverse("contas:usuarios"), {"setor": "1;x"}).status_code == 200


def test_adm_move_fluxo_e_gestor_nao(
    cliente_adm, cliente_coordenador, usuario_coordenador, outro_setor
):
    fluxo = demo.criar_fluxo(usuario_coordenador, "F", "ativo")
    url = reverse("fluxos:editar", kwargs={"pk": fluxo.pk})
    cliente_coordenador.post(url, {"nome": "F", "descricao": "", "setor": outro_setor.pk})
    fluxo.refresh_from_db()
    assert fluxo.setor.nome == "Geral"
    cliente_adm.post(url, {"nome": "F", "descricao": "", "setor": outro_setor.pk})
    fluxo.refresh_from_db()
    assert fluxo.setor == outro_setor
    r = cliente_adm.post(url, {"nome": "F", "descricao": "", "setor": "999999"})
    assert r.status_code == 200
    fluxo.refresh_from_db()
    assert fluxo.setor == outro_setor
    ctx = cliente_adm.get(reverse("fluxos:lista")).context
    assert ctx["pode_mover_setor"] and ctx["opcoes_setor"]
    assert not cliente_coordenador.get(reverse("fluxos:lista")).context["pode_mover_setor"]


def test_menu_do_adm_tem_inicio_e_setores(cliente_adm):
    chaves = [i["chave"] for i in cliente_adm.get(reverse("contas:setores")).context["menu"]]
    assert chaves[0] == "inicio" and "setores" in chaves
    ativos = [
        i["chave"] for i in cliente_adm.get(reverse("contas:setores")).context["menu"] if i["ativo"]
    ]
    assert ativos == ["setores"]
