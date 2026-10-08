import importlib

import pytest
from django.urls import reverse

from apps.contas.models import Setor
from apps.contas.permissoes import escopo, pode
from apps.execucoes import demo as demo_exec
from apps.execucoes.models import Execucao
from apps.fluxos import demo
from apps.fluxos.models import Fluxo
from apps.motor import executor
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m4"), pytest.mark.django_db]


@pytest.fixture
def coord_fin(outro_setor):
    return criar_usuario("fin@exemplo.test", "Fin Coord", "Coordenador", setor=outro_setor)


@pytest.fixture
def base_fin(outro_setor):
    return criar_usuario("basefin@exemplo.test", "Fin Base", "Base", setor=outro_setor)


def test_fluxo_nasce_no_setor_do_dono_e_mudar_usuario_nao_move(usuario_coordenador, outro_setor):
    fluxo = demo.criar_fluxo(usuario_coordenador, "F", "ativo")
    assert fluxo.setor == usuario_coordenador.setor
    usuario_coordenador.setor = outro_setor
    usuario_coordenador.save()
    fluxo.refresh_from_db()
    assert fluxo.setor.nome == "Geral"


def test_escopo_fluxos_por_papel_e_setor(usuario_adm, usuario_coordenador, usuario_base, coord_fin):
    do_geral = demo.criar_fluxo(usuario_coordenador, "Geral A", "ativo")
    rascunho = demo.criar_fluxo(usuario_coordenador, "Geral R")
    do_fin = demo.criar_fluxo(coord_fin, "Fin A", "ativo")
    assert set(escopo(usuario_adm, Fluxo.objects)) == {do_geral, rascunho, do_fin}
    assert set(escopo(usuario_coordenador, Fluxo.objects)) == {do_geral, rascunho}
    assert set(escopo(coord_fin, Fluxo.objects)) == {do_fin}
    assert set(escopo(usuario_base, Fluxo.objects)) == {do_geral}
    assert pode(usuario_coordenador, "fluxos.editar", do_geral)
    assert not pode(usuario_coordenador, "fluxos.editar", do_fin)
    assert not pode(usuario_base, "fluxos.executar", do_fin)
    assert not pode(usuario_base, "fluxos.executar", rascunho)


def test_usuario_sem_setor_nao_enxerga_nada(usuario_coordenador):
    demo.criar_fluxo(usuario_coordenador, "F", "ativo")
    sem_setor = criar_usuario("sem2@exemplo.test", "Sem", "Coordenador", setor=None)
    assert not escopo(sem_setor, Fluxo.objects).exists()
    base = criar_usuario("sem3@exemplo.test", "Sem", "Base", setor=None)
    assert not escopo(base, Fluxo.objects).exists()


def test_escopo_execucoes(usuario_adm, usuario_coordenador, usuario_base, coord_fin, base_fin):
    a = demo_exec.criar_execucao(usuario_base)
    b = demo_exec.criar_execucao(usuario_coordenador)
    c = demo_exec.criar_execucao(base_fin)
    assert set(escopo(usuario_adm, Execucao.objects)) == {a, b, c}
    assert set(escopo(usuario_coordenador, Execucao.objects)) == {a, b}
    assert set(escopo(coord_fin, Execucao.objects)) == {c}
    assert set(escopo(usuario_base, Execucao.objects)) == {a}


@pytest.mark.parametrize(
    ("rota", "metodo", "extra"),
    [
        ("fluxos:editor", "get", {}),
        ("fluxos:editar", "post", {"nome": "X"}),
        ("fluxos:excluir", "post", {}),
        ("fluxos:status", "post", {"status": "ativo"}),
        ("fluxos:executar", "post", {}),
        ("fluxos:salvar_grafo", "post", {}),
    ],
)
def test_idor_fluxo_de_outro_setor_404(cliente_coordenador, coord_fin, rota, metodo, extra):
    alheio = demo.criar_fluxo(coord_fin, "Alheio", "ativo", demo.grafo_exemplo())
    resposta = getattr(cliente_coordenador, metodo)(reverse(rota, kwargs={"pk": alheio.pk}), extra)
    assert resposta.status_code == 404
    alheio.refresh_from_db()
    assert alheio.nome == "Alheio"


def test_idor_execucao_de_outro_setor_404(cliente_coordenador, base_fin):
    alheia = demo_exec.criar_execucao(base_fin)
    assert (
        cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": alheia.pk})).status_code
        == 404
    )
    lista = cliente_coordenador.get(reverse("execucoes:lista"))
    assert alheia not in list(lista.context["page_obj"])


def test_base_de_outro_setor_nao_executa_nem_ve(cliente_base, coord_fin):
    alheio = demo.criar_fluxo(coord_fin, "Alheio", "ativo", demo.grafo_exemplo())
    assert (
        cliente_base.post(reverse("fluxos:executar", kwargs={"pk": alheio.pk})).status_code == 404
    )
    assert Execucao.objects.count() == 0


def test_executor_grava_setor_do_fluxo(usuario_adm, coord_fin):
    fluxo = demo.criar_fluxo(
        coord_fin, "Bloqueado", "ativo", demo.grafo_exemplo(url="http://127.0.0.1:9/x")
    )
    execucao = executor.executar(fluxo, usuario_adm)  # adm do Geral executa fluxo do Financeiro
    assert execucao.setor == fluxo.setor == coord_fin.setor
    fluxo.setor = Setor.objects.get(nome="Geral")
    fluxo.save()
    execucao.refresh_from_db()
    assert execucao.setor.nome == "Financeiro"


def test_migration_de_dados_cria_geral_e_vincula():
    modulo = importlib.import_module("apps.contas.migrations.0004_setor_geral")
    from django.apps import apps

    usuario = criar_usuario("solto@exemplo.test", "Solto", "Base", setor=None)
    fluxo = demo.criar_fluxo(usuario, "Solto")
    Fluxo.objects.filter(pk=fluxo.pk).update(setor=None)
    modulo.criar_geral(apps, None)
    usuario.refresh_from_db()
    fluxo.refresh_from_db()
    assert usuario.setor.nome == fluxo.setor.nome == "Geral"
    assert Setor.objects.filter(nome="Geral").count() == 1
