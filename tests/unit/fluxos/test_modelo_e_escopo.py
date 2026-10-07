import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.contas import permissoes
from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = [pytest.mark.modulo("m2"), pytest.mark.django_db]


def _fluxo(dono, nome="F", status="rascunho"):
    return Fluxo.objects.create(nome=nome, dono=dono, status=status)


def test_defaults(usuario_adm):
    fluxo = _fluxo(usuario_adm)
    assert fluxo.status == "rascunho"
    assert fluxo.grafo == grafo_inicial()
    assert fluxo.descricao == ""
    assert fluxo.criado_em and fluxo.atualizado_em
    assert str(fluxo) == "F"


def test_atualizado_em_muda_ao_salvar(usuario_adm):
    fluxo = _fluxo(usuario_adm)
    antes = fluxo.atualizado_em
    fluxo.nome = "Outro"
    fluxo.save()
    assert fluxo.atualizado_em > antes


def test_grafo_inicial_nao_e_compartilhado(usuario_adm):
    a, b = _fluxo(usuario_adm), _fluxo(usuario_adm)
    a.grafo["nos"].append("x")
    assert b.grafo == grafo_inicial()


def test_escopo_por_papel(usuario_adm, usuario_coordenador, usuario_base):
    _fluxo(usuario_adm, "R", "rascunho")
    _fluxo(usuario_adm, "A", "ativo")
    nomes = lambda u: sorted(permissoes.escopo(u, Fluxo.objects).values_list("nome", flat=True))  # noqa: E731
    assert nomes(usuario_adm) == ["A", "R"]
    assert nomes(usuario_coordenador) == ["A", "R"]
    assert nomes(usuario_base) == ["A"]


def test_pode_com_objeto_para_base(usuario_base, usuario_adm):
    rascunho, ativo = _fluxo(usuario_adm, "R"), _fluxo(usuario_adm, "A", "ativo")
    assert not permissoes.pode(usuario_base, "fluxos.executar", rascunho)
    assert permissoes.pode(usuario_base, "fluxos.executar", ativo)
    assert not permissoes.pode(usuario_base, "fluxos.editar")
    assert permissoes.pode(usuario_adm, "fluxos.editar", rascunho)


def test_escopo_e_uma_query_so(usuario_base, usuario_adm):
    for i in range(5):
        _fluxo(usuario_adm, f"F{i}", "ativo")
    with CaptureQueriesContext(connection) as consultas:
        list(permissoes.escopo(usuario_base, Fluxo.objects).select_related("dono"))
    assert len(consultas) == 2 - 1 + 1  # 1 consulta do escopo + 1 do papel (grupos do usuário)
