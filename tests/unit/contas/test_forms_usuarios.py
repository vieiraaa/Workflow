import pytest
from django.contrib.auth.models import Group
from django.db import transaction

from apps.contas.forms_usuarios import (
    MSG_AUTOPROTECAO,
    MSG_EMAIL_DUPLICADO,
    MSG_SENHAS_DIFERENTES,
    MSG_ULTIMO_ADM,
    RedefinirSenhaForm,
    UsuarioEditarForm,
    UsuarioNovoForm,
)
from apps.contas.models import Setor
from tests.conftest import SENHA_TESTE, criar_usuario

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]


def _novo(**sobrescritas):
    dados = {
        "nome": "Maria",
        "email": "maria@exemplo.test",
        "papel": "base",
        "setor": str(Setor.objects.get_or_create(nome="Geral")[0].pk),
        "senha": SENHA_TESTE,
        "confirmacao": SENHA_TESTE,
    }
    return UsuarioNovoForm({**dados, **sobrescritas})


def _editar(usuario, editor, **mudancas):
    dados = {**UsuarioEditarForm.valores_iniciais(usuario), **mudancas}
    dados = {k: v for k, v in dados.items() if v is not False}  # checkbox desmarcado não é enviado
    with transaction.atomic():
        return UsuarioEditarForm(dados, instance=usuario, editor=editor)


def test_novo_valido_cria_usuario_com_papel_unico():
    form = _novo(email="  Maria@Exemplo.TEST ", papel="coordenador")
    assert form.is_valid(), form.errors
    usuario = form.salvar()
    assert usuario.email == "maria@exemplo.test"
    assert list(usuario.groups.values_list("name", flat=True)) == ["Coordenador"]
    assert usuario.check_password(SENHA_TESTE)


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("papel", "", "Escolha um papel."),
        ("papel", "Adm", "Papel inválido."),
        ("nome", "", "Este campo é obrigatório."),
        ("confirmacao", "outra-senha-forte-1", MSG_SENHAS_DIFERENTES),
    ],
)
def test_novo_erros_com_mensagem_exata(campo, valor, mensagem):
    form = _novo(**{campo: valor})
    assert not form.is_valid()
    assert mensagem in form.errors[campo]


@pytest.mark.parametrize("senha", ["curta1", "123456789012", "password1234"])
def test_novo_senha_fraca(senha):
    assert not _novo(senha=senha, confirmacao=senha).is_valid()


def test_novo_email_duplicado_sem_diferenciar_caixa(usuario_base):
    form = _novo(email=usuario_base.email.upper())
    assert not form.is_valid()
    assert form.errors["email"] == [MSG_EMAIL_DUPLICADO]


def test_novo_nome_acima_de_120():
    assert not _novo(nome="n" * 121).is_valid()
    assert _novo(nome="n" * 120).is_valid()


def test_editar_altera_dados_e_papel(usuario_adm, usuario_base):
    form = _editar(usuario_base, usuario_adm, nome="Novo", papel="coordenador", ativo="on")
    assert form.is_valid(), form.errors
    form.salvar()
    usuario_base.refresh_from_db()
    assert usuario_base.nome == "Novo"
    assert list(usuario_base.groups.values_list("name", flat=True)) == ["Coordenador"]


def test_editar_email_duplicado_exclui_o_proprio(usuario_adm, usuario_base, usuario_coordenador):
    assert _editar(usuario_base, usuario_adm).is_valid()
    form = _editar(usuario_base, usuario_adm, email=usuario_coordenador.email.upper())
    assert form.errors["email"] == [MSG_EMAIL_DUPLICADO]


@pytest.mark.parametrize(
    ("mudanca", "campo"), [({"ativo": False}, "ativo"), ({"papel": "base"}, "papel")]
)
def test_adm_nao_se_rebaixa_nem_se_desativa(usuario_adm, mudanca, campo):
    form = _editar(usuario_adm, usuario_adm, **mudanca)
    assert not form.is_valid()
    assert form.errors[campo] == [MSG_AUTOPROTECAO]


def test_nunca_zero_adm_ativo(usuario_adm, usuario_coordenador):
    criar_usuario("inativo@exemplo.test", "Inativo", "Adm", is_active=False)  # não conta
    form = _editar(usuario_adm, usuario_coordenador, ativo=False)
    assert form.errors["ativo"] == [MSG_ULTIMO_ADM]


def test_dois_adms_permitem_desativar_o_outro(usuario_adm):
    segundo = criar_usuario("adm2@exemplo.test", "Adm Dois", "Adm")
    assert _editar(segundo, usuario_adm, ativo=False).is_valid()


def test_redefinir_senha(usuario_base):
    form = RedefinirSenhaForm(
        {"nova_senha": "Redefinida-Forte-31", "confirmacao": "Redefinida-Forte-31"},
        instance=usuario_base,
    )
    assert form.is_valid(), form.errors
    form.salvar()
    usuario_base.refresh_from_db()
    assert usuario_base.check_password("Redefinida-Forte-31")


@pytest.mark.parametrize(
    ("nova", "confirmacao"),
    [("Redefinida-Forte-31", "Outra-Forte-32"), ("curta1", "curta1"), ("", "")],
)
def test_redefinir_senha_invalida(usuario_base, nova, confirmacao):
    form = RedefinirSenhaForm(
        {"nova_senha": nova, "confirmacao": confirmacao}, instance=usuario_base
    )
    assert not form.is_valid()


def test_grupos_existem():
    assert Group.objects.filter(name="Adm").exists()


@pytest.mark.parametrize("senha", ["aaaaaaaaaaaa", "abababababab"])
def test_senha_repetitiva_recusada(senha):
    assert not _novo(senha=senha, confirmacao=senha).is_valid()


def test_ultimo_adm_ao_mudar_papel_erro_no_campo_papel(usuario_adm, usuario_coordenador):
    form = _editar(usuario_adm, usuario_coordenador, papel="base")
    assert form.errors["papel"] == [MSG_ULTIMO_ADM]
