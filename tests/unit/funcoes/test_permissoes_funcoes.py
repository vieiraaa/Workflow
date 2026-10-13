import pytest

from apps.contas.permissoes import escopo, pode
from apps.fluxos.models import Fluxo
from apps.funcoes.models import Funcao
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m7a"), pytest.mark.django_db]


@pytest.fixture
def fluxo(usuario_adm):
    return Fluxo.objects.create(nome="F", dono=usuario_adm)


def _funcao(fluxo, usuario, nome, **extra):
    extra.setdefault("versao", 1)
    return Funcao.objects.create(nome=nome, fluxo=fluxo, criada_por=usuario, **extra)


def test_matriz_das_acoes(usuario_adm, usuario_coordenador, usuario_base):
    assert pode(usuario_adm, "funcoes.gerenciar")
    assert not pode(usuario_coordenador, "funcoes.gerenciar")
    assert not pode(usuario_base, "funcoes.gerenciar")
    assert pode(usuario_base, "funcoes.ver") and pode(usuario_coordenador, "funcoes.executar")


def test_escopo_liberadas(fluxo, usuario_adm, usuario_coordenador, usuario_base, outro_setor):
    todos = _funcao(fluxo, usuario_adm, "Todos")
    rascunho = _funcao(fluxo, usuario_adm, "Rascunho", versao=0)
    inativa = _funcao(fluxo, usuario_adm, "Inativa", ativa=False)
    do_setor = _funcao(fluxo, usuario_adm, "Setor", liberar_para="setores")
    do_setor.setores.add(usuario_base.setor)
    de_outro = _funcao(fluxo, usuario_adm, "Outro", liberar_para="setores")
    de_outro.setores.add(outro_setor)
    so_base = _funcao(fluxo, usuario_adm, "Base", liberar_para="papeis", papeis=["base"])
    so_coord = _funcao(fluxo, usuario_adm, "Coord", liberar_para="papeis", papeis=["coordenador"])

    vistas = set(escopo(usuario_base, Funcao.objects))
    assert vistas == {todos, do_setor, so_base}
    assert set(escopo(usuario_coordenador, Funcao.objects)) == {todos, do_setor, so_coord}
    assert escopo(usuario_adm, Funcao.objects).count() == 7
    for f in (rascunho, inativa, de_outro, so_coord):
        assert not pode(usuario_base, "funcoes.ver", f)
    assert pode(usuario_base, "funcoes.ver", do_setor) and pode(
        usuario_base, "funcoes.ver", so_base
    )


def test_usuario_sem_setor_so_ve_todos_e_papel(fluxo, usuario_adm):
    sem_setor = criar_usuario("semsetor@exemplo.test", "Sem Setor", "Base", setor=None)
    sem_setor.setor = None
    sem_setor.save()
    todos = _funcao(fluxo, usuario_adm, "Todos")
    _funcao(fluxo, usuario_adm, "Setor", liberar_para="setores")
    assert set(escopo(sem_setor, Funcao.objects)) == {todos}
