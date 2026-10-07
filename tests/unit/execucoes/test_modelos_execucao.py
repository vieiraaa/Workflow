from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contas import permissoes
from apps.execucoes.models import Execucao, ExecucaoNo
from apps.fluxos import demo
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m3"), pytest.mark.django_db]


def _execucao(usuario, fluxo=None, **extra):
    return Execucao.objects.create(
        fluxo=fluxo, fluxo_nome=extra.pop("fluxo_nome", "F"), executado_por=usuario, **extra
    )


def _no(execucao, no_id, tipo, ordem, status="sucesso"):
    return ExecucaoNo.objects.create(
        execucao=execucao, no_id=no_id, no_tipo=tipo, ordem=ordem, status=status
    )


def test_defaults_e_str(usuario_adm):
    execucao = _execucao(usuario_adm)
    assert execucao.status == "executando" and execucao.grafo_snapshot == {}
    assert execucao.finalizada_em is None and execucao.duracao_ms is None
    assert str(execucao).startswith("F · ")


def test_duracao_em_ms(usuario_adm):
    inicio = timezone.now()
    execucao = _execucao(
        usuario_adm, iniciada_em=inicio, finalizada_em=inicio + timedelta(milliseconds=1500)
    )
    assert execucao.duracao_ms == 1500


def test_executando_ha_mais_de_5_minutos_aparece_como_erro_interrompida(usuario_adm):
    velha = _execucao(usuario_adm, iniciada_em=timezone.now() - timedelta(minutes=6))
    recente = _execucao(usuario_adm, iniciada_em=timezone.now() - timedelta(minutes=4))
    assert velha.status_efetivo == "erro" and velha.erro_resumo_efetivo == "Execução interrompida"
    assert velha.status_rotulo == "Erro"
    assert recente.status_efetivo == "executando" and recente.erro_resumo_efetivo == ""
    velha.refresh_from_db()
    assert velha.status == "executando"  # só a exibição muda; o banco não é reescrito


def test_so_executando_vira_interrompida(usuario_adm):
    ok = _execucao(usuario_adm, status="sucesso", iniciada_em=timezone.now() - timedelta(hours=1))
    assert ok.status_efetivo == "sucesso"


def test_snapshot_e_nome_sobrevivem_a_exclusao_do_fluxo(usuario_adm):
    fluxo = demo.criar_fluxo(usuario_adm, "Original", "ativo", demo.grafo_exemplo())
    execucao = _execucao(usuario_adm, fluxo, fluxo_nome=fluxo.nome, grafo_snapshot=fluxo.grafo)
    ExecucaoNo.objects.create(
        execucao=execucao, no_id="n1", no_tipo="gatilho", ordem=0, status="sucesso"
    )
    fluxo.delete()
    execucao.refresh_from_db()
    assert execucao.fluxo is None and execucao.fluxo_nome == "Original"
    assert execucao.grafo_snapshot["nos"][0]["id"] == "n1"
    assert execucao.nos.count() == 1


def test_editar_o_fluxo_nao_altera_o_snapshot(usuario_adm):
    fluxo = demo.criar_fluxo(usuario_adm, "F", "ativo", demo.grafo_exemplo())
    execucao = _execucao(usuario_adm, fluxo, grafo_snapshot=fluxo.grafo)
    fluxo.grafo = {"versao": 1, "nos": [], "arestas": []}
    fluxo.save()
    execucao.refresh_from_db()
    assert len(execucao.grafo_snapshot["nos"]) == 3


def test_ordem_do_no_e_unica_por_execucao(usuario_adm):
    execucao = _execucao(usuario_adm)
    ExecucaoNo.objects.create(
        execucao=execucao, no_id="a", no_tipo="gatilho", ordem=0, status="sucesso"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ExecucaoNo.objects.create(
            execucao=execucao, no_id="b", no_tipo="http", ordem=0, status="erro"
        )


def test_nos_vem_em_ordem_e_cascata_na_exclusao(usuario_adm):
    execucao = _execucao(usuario_adm)
    for ordem, no_id in ((2, "c"), (0, "a"), (1, "b")):
        ExecucaoNo.objects.create(
            execucao=execucao, no_id=no_id, no_tipo="http", ordem=ordem, status="sucesso"
        )
    assert [n.no_id for n in execucao.nos.all()] == ["a", "b", "c"]
    execucao.delete()
    assert ExecucaoNo.objects.count() == 0


def test_escopo_adm_coordenador_todas_base_so_as_proprias(
    usuario_adm, usuario_coordenador, usuario_base
):
    outro_base = criar_usuario("base2@exemplo.test", "Outra Base", "Base")
    _execucao(usuario_base, fluxo_nome="minha")
    _execucao(outro_base, fluxo_nome="de outro")
    _execucao(usuario_adm, fluxo_nome="do adm")
    nomes = lambda u: sorted(  # noqa: E731
        permissoes.escopo(u, Execucao.objects).values_list("fluxo_nome", flat=True)
    )
    assert nomes(usuario_adm) == ["de outro", "do adm", "minha"]
    assert nomes(usuario_coordenador) == ["de outro", "do adm", "minha"]
    assert nomes(usuario_base) == ["minha"]


def test_pode_ver_objeto_so_se_proprio_para_base(usuario_base, usuario_adm):
    minha = _execucao(usuario_base)
    alheia = _execucao(usuario_adm)
    assert permissoes.pode(usuario_base, "execucoes.ver", minha)
    assert not permissoes.pode(usuario_base, "execucoes.ver", alheia)
    assert permissoes.pode(usuario_adm, "execucoes.ver", alheia)


def test_escopo_da_lista_com_select_related_e_constante(usuario_base):
    def consultar():
        with CaptureQueriesContext(connection) as consultas:
            for e in permissoes.escopo(usuario_base, Execucao.objects).select_related(
                "executado_por", "fluxo"
            ):
                e.executado_por.nome  # noqa: B018
        return len(consultas)

    _execucao(usuario_base)
    consultar()  # aquece o cache de papel da instância
    um = consultar()
    for _ in range(10):
        _execucao(usuario_base)
    assert consultar() == um
