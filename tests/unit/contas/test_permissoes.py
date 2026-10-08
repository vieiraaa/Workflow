from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser, Group

from apps.contas import permissoes
from apps.contas.models import Usuario

pytestmark = [pytest.mark.modulo("m0"), pytest.mark.django_db]


def test_grupos_dos_papeis_existem_apos_migrate():
    assert set(Group.objects.values_list("name", flat=True)) >= {"Adm", "Coordenador", "Base"}


@pytest.mark.parametrize(
    ("fixture", "papel"),
    [("usuario_adm", "adm"), ("usuario_coordenador", "coordenador"), ("usuario_base", "base")],
)
def test_papel_de(request, fixture, papel):
    assert permissoes.papel_de(request.getfixturevalue(fixture)) == papel


def test_sem_papel_e_anonimo_sem_nenhuma_permissao(usuario_sem_papel):
    for usuario in (usuario_sem_papel, AnonymousUser(), None):
        assert permissoes.papel_de(usuario) is None
        assert not permissoes.pode(usuario, "fluxos.ver")


def test_superuser_nao_ganha_bypass():
    su = Usuario.objects.create_superuser("su@exemplo.test", "SenhaForte#12345", nome="Su")
    assert not permissoes.pode(su, "usuarios.gerenciar")


def test_usuario_com_dois_papeis_nao_tem_papel(usuario_adm):
    usuario_adm.groups.add(Group.objects.get(name="Base"))
    usuario_adm.__dict__.pop("_papel_cache", None)
    assert permissoes.papel_de(usuario_adm) is None


def test_matriz_da_spec(usuario_adm, usuario_coordenador, usuario_base):
    assert permissoes.pode(usuario_adm, "usuarios.gerenciar")
    assert not permissoes.pode(usuario_coordenador, "usuarios.gerenciar")
    assert permissoes.pode(usuario_coordenador, "fluxos.editar")
    assert not permissoes.pode(usuario_base, "fluxos.editar")
    assert permissoes.pode(usuario_base, "conta.trocar_senha")


def test_escopo_ativos_e_proprias_em_objetos(usuario_base):
    setor = usuario_base.setor_id
    assert permissoes.pode(
        usuario_base, "fluxos.executar", SimpleNamespace(status="ativo", setor_id=setor)
    )
    assert not permissoes.pode(
        usuario_base, "fluxos.executar", SimpleNamespace(status="rascunho", setor_id=setor)
    )
    assert not permissoes.pode(
        usuario_base, "fluxos.executar", SimpleNamespace(status="ativo", setor_id=setor + 1)
    )
    assert permissoes.pode(
        usuario_base, "execucoes.ver", SimpleNamespace(executado_por_id=usuario_base.pk)
    )
    assert not permissoes.pode(usuario_base, "execucoes.ver", SimpleNamespace(executado_por_id=0))


def test_acao_desconhecida_levanta():
    with pytest.raises(KeyError):
        permissoes.pode(AnonymousUser(), "nao.existe")


def test_escopo_de_queryset(usuario_adm, usuario_base, usuario_sem_papel):
    qs = Usuario.objects.all()
    assert permissoes.escopo(usuario_adm, qs, "fluxos.ver").count() == qs.count()
    assert permissoes.escopo(usuario_sem_papel, qs, "fluxos.ver").count() == 0
    assert permissoes.escopo(usuario_base, qs, "usuarios.gerenciar").count() == 0


def test_escopo_ativos_e_proprias_filtram_no_banco(usuario_base):
    from unittest.mock import MagicMock

    qs = MagicMock()
    qs.all.return_value = qs
    qs.model._meta.get_fields.return_value = [SimpleNamespace(name="setor")]
    permissoes.escopo(usuario_base, qs, "fluxos.ver")
    qs.filter.assert_called_once_with(setor=usuario_base.setor_id)
    qs.filter.return_value.filter.assert_called_once_with(status="ativo")
    qs.reset_mock()
    permissoes.escopo(usuario_base, qs, "execucoes.ver")
    qs.filter.assert_called_once_with(executado_por=usuario_base)


def test_escopo_infere_acao_pelo_modelo(usuario_base):
    from unittest.mock import MagicMock

    qs = MagicMock()
    qs.all.return_value = qs
    qs.model._meta.label_lower = "fluxos.fluxo"
    qs.model._meta.get_fields.return_value = [SimpleNamespace(name="setor")]
    permissoes.escopo(usuario_base, qs)
    qs.filter.return_value.filter.assert_called_once_with(status="ativo")


def test_nome_do_papel(usuario_adm, usuario_base, usuario_sem_papel):
    assert permissoes.nome_do_papel(usuario_adm) == "Administrador"
    assert permissoes.nome_do_papel(usuario_base) == "Usuário base"
    assert permissoes.nome_do_papel(usuario_sem_papel) == ""
