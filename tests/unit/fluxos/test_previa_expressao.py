"""Prévia de expressão (T-063, MV2-23): usa a última execução de teste, nunca executa nada."""

import json

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.execucoes.models import Execucao, ExecucaoNo
from apps.fluxos import demo

pytestmark = [pytest.mark.modulo("m5"), pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _limpar_limite():
    cache.clear()


def _previa(cliente, fluxo, **corpo):
    padrao = {"no_id": "n2", "campo": "url", "expressao": "{{ $json.id }}"}
    return cliente.post(
        reverse("fluxos:previa_expressao", kwargs={"pk": fluxo.pk}),
        json.dumps({**padrao, **corpo}),
        content_type="application/json",
    )


def _execucao_de_teste(fluxo, usuario, teste=True):
    execucao = Execucao.objects.create(
        fluxo=fluxo,
        fluxo_nome=fluxo.nome,
        grafo_snapshot=fluxo.grafo,
        executado_por=usuario,
        setor_id=fluxo.setor_id,
        status="sucesso",
        iniciada_em=timezone.now(),
        teste=teste,
    )
    dados = [{"json": {"id": 7, "token": "ficticio"}}, {"json": {"id": 8}}]
    ExecucaoNo.objects.create(
        execucao=execucao, no_id="n1", no_tipo="gatilho", no_titulo="Início", ordem=0,
        status="sucesso", saida=dados, itens_saida=2,
    )  # fmt: skip
    ExecucaoNo.objects.create(
        execucao=execucao, no_id="n2", no_tipo="http", no_titulo="Buscar pedido", ordem=1,
        status="nao_executado", entrada=dados, itens_entrada=2,
    )  # fmt: skip
    return execucao


@pytest.fixture
def fluxo(usuario_adm):
    return demo.criar_fluxo(usuario_adm, "F", "rascunho", demo.grafo_exemplo())


def test_sem_execucao_de_teste_pede_para_executar(cliente_adm, fluxo):
    corpo = _previa(cliente_adm, fluxo).json()
    assert corpo == {"ok": False, "erro": "Execute o fluxo em teste para ver a prévia."}


def test_avalia_sobre_o_item_0_do_no(cliente_adm, usuario_adm, fluxo):
    _execucao_de_teste(fluxo, usuario_adm)
    corpo = _previa(cliente_adm, fluxo).json()
    assert corpo == {"ok": True, "valor": 7, "texto": "7", "itens_usados": 2}
    mista = _previa(cliente_adm, fluxo, expressao="id={{ $json.id }}").json()
    assert mista["texto"] == "id=7"
    outro_no = _previa(cliente_adm, fluxo, expressao="{{ $('Início').first().json.id }}").json()
    assert outro_no["valor"] == 7


def test_ignora_execucao_que_nao_e_de_teste_ou_de_outra_pessoa(
    cliente_adm, usuario_adm, usuario_coordenador, fluxo
):
    _execucao_de_teste(fluxo, usuario_adm, teste=False)
    _execucao_de_teste(fluxo, usuario_coordenador)
    assert _previa(cliente_adm, fluxo).json()["ok"] is False


def test_erro_de_expressao_e_limite_de_tamanho(cliente_adm, usuario_adm, fluxo):
    _execucao_de_teste(fluxo, usuario_adm)
    assert _previa(cliente_adm, fluxo, expressao="{{ $json. }}").json()["ok"] is False
    grande = _previa(cliente_adm, fluxo, expressao="a" * 2001).json()
    assert grande["ok"] is False and "2.000" in grande["erro"]


def test_corpo_invalido_e_permissoes(cliente_adm, cliente_base, cliente_anonimo, fluxo):
    assert _previa(cliente_adm, fluxo, no_id=3).status_code == 400
    assert _previa(cliente_base, fluxo).status_code == 403
    assert _previa(cliente_anonimo, fluxo).status_code == 302
    url = reverse("fluxos:previa_expressao", kwargs={"pk": fluxo.pk})
    assert cliente_adm.get(url).status_code == 405


def test_limite_de_30_por_minuto(cliente_adm, fluxo):
    for _ in range(30):
        assert _previa(cliente_adm, fluxo).status_code == 200
    assert _previa(cliente_adm, fluxo).status_code == 429
