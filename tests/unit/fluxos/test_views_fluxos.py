import json

import pytest
from django.core.management import call_command
from django.core.paginator import Paginator
from django.urls import reverse

from apps.fluxos import demo
from apps.fluxos.models import Fluxo
from apps.nucleo import listagem

pytestmark = [pytest.mark.modulo("m2"), pytest.mark.django_db]


def _post(cliente, fluxo, corpo, **extra):
    return cliente.post(
        reverse("fluxos:salvar_grafo", kwargs={"pk": fluxo.pk}),
        json.dumps(corpo),
        content_type="application/json",
        **extra,
    )


def test_listagem_pagina_valida_e_consulta():
    paginator = Paginator(list(range(60)), 25)
    assert listagem.pagina_valida(paginator, "abc").number == 1
    assert listagem.pagina_valida(paginator, "-5").number == 1
    assert listagem.pagina_valida(paginator, "99").number == 3
    assert listagem.consulta({"q": "a b", "ordem": "-x", "status": ""}, {"ordem": "-x"}) == "q=a+b"


def test_salvar_resposta_traz_status_e_volta_para_rascunho(cliente_adm, usuario_adm):
    fluxo = demo.criar_fluxo(usuario_adm, "F", "ativo", demo.grafo_exemplo())
    sem_saida = demo.grafo_exemplo()
    sem_saida["nos"].pop()
    sem_saida["arestas"].pop()
    resposta = _post(
        cliente_adm, fluxo, {"grafo": sem_saida, "atualizado_em": fluxo.atualizado_em.isoformat()}
    )
    corpo = resposta.json()
    assert corpo["voltou_para_rascunho"] is True and corpo["status"] == "rascunho"
    fluxo.refresh_from_db()
    assert fluxo.status == "rascunho"
    assert corpo["atualizado_em"] == fluxo.atualizado_em.isoformat()


def test_salvar_valido_em_ativo_nao_volta(cliente_adm, usuario_adm):
    fluxo = demo.criar_fluxo(usuario_adm, "F", "ativo", demo.grafo_exemplo())
    resposta = _post(
        cliente_adm,
        fluxo,
        {"grafo": demo.grafo_exemplo(), "atualizado_em": fluxo.atualizado_em.isoformat()},
    )
    assert resposta.json()["voltou_para_rascunho"] is False and resposta.json()["status"] == "ativo"


@pytest.mark.parametrize("valor", ["lixo", "", "2026-13-45T00:00:00"])
def test_atualizado_em_invalido_400(cliente_adm, usuario_adm, valor):
    fluxo = demo.criar_fluxo(usuario_adm, "F")
    resposta = _post(cliente_adm, fluxo, {"grafo": demo.grafo_exemplo(), "atualizado_em": valor})
    assert resposta.status_code == 400


def test_status_ativar_ok_json_e_voltar_para_lista(cliente_adm, usuario_adm):
    fluxo = demo.criar_fluxo(usuario_adm, "F", "rascunho", demo.grafo_exemplo())
    url = reverse("fluxos:status", kwargs={"pk": fluxo.pk})
    resposta = cliente_adm.post(url, {"status": "ativo"}, HTTP_ACCEPT="application/json")
    assert resposta.status_code == 200 and resposta.json() == {"ok": True, "status": "ativo"}
    resposta = cliente_adm.post(url, {"status": "rascunho", "voltar": "lista"})
    assert resposta.status_code == 302 and resposta.url == reverse("fluxos:lista")


def test_status_ativar_grafo_corrompido_vira_pendencia(cliente_adm, usuario_adm):
    fluxo = Fluxo.objects.create(nome="F", dono=usuario_adm, grafo={"versao": 9})
    resposta = cliente_adm.post(
        reverse("fluxos:status", kwargs={"pk": fluxo.pk}),
        {"status": "ativo"},
        HTTP_ACCEPT="application/json",
    )
    assert resposta.status_code == 400 and resposta.json()["pendencias"]


def test_executar_placeholder_e_escopo(cliente_base, cliente_coordenador, usuario_adm):
    ativo = demo.criar_fluxo(usuario_adm, "Ativo", "ativo", demo.grafo_exemplo())
    rascunho = demo.criar_fluxo(usuario_adm, "Rascunho")
    url = lambda f: reverse("fluxos:executar", kwargs={"pk": f.pk})  # noqa: E731
    assert cliente_base.post(url(ativo)).status_code == 302
    assert cliente_base.post(url(rascunho)).status_code == 404
    assert cliente_coordenador.post(url(rascunho)).status_code == 302
    assert cliente_base.get(url(ativo)).status_code == 405


def test_semear_demo_cria_fluxos_e_e_idempotente(capsys):
    call_command("semear_demo", senha="SenhaForte#12345")
    total = Fluxo.objects.count()
    assert total == len(demo.EXEMPLOS)
    call_command("semear_demo", senha="SenhaForte#12345")
    assert Fluxo.objects.count() == total
    assert Fluxo.objects.filter(status="ativo").count() == 2


@pytest.mark.parametrize(
    "bruto",
    [
        '{"grafo": {"versao": 1, "nos": [], "arestas": [], "x": NaN}, "atualizado_em": "a"}',
        '{"grafo": {"versao": 1, "nos": [], "arestas": [], "x": 1e999}, "atualizado_em": "a"}',
        '{"grafo": {"versao": 1, "nos": [], "arestas": [], "x": '
        + "[" * 100000
        + "]" * 100000
        + "}}",
        '{"grafo": {"versao": 1, "nos": [{"id": "n1", "tipo": "gatilho", "titulo": "\\ud800",'
        '"posicao": {"x": 1, "y": 1}, "config": {}}], "arestas": []}, "atualizado_em": "a"}',
    ],
)
def test_json_hostil_vira_400_sem_gravar(cliente_adm, usuario_adm, bruto):
    fluxo = demo.criar_fluxo(usuario_adm, "F")
    antes = fluxo.grafo
    resposta = cliente_adm.post(
        reverse("fluxos:salvar_grafo", kwargs={"pk": fluxo.pk}),
        bruto,
        content_type="application/json",
    )
    assert resposta.status_code == 400 and resposta.json()["ok"] is False
    fluxo.refresh_from_db()
    assert fluxo.grafo == antes


def test_modelo_valida_o_grafo_em_qualquer_entrada(usuario_adm):
    from django.core.exceptions import ValidationError

    fluxo = Fluxo(nome="F", dono=usuario_adm, grafo={"versao": 1, "nos": [], "arestas": [], "x": 1})
    with pytest.raises(ValidationError) as erro:
        fluxo.full_clean()
    assert "grafo" in erro.value.message_dict
    with pytest.raises(ValidationError):
        demo.criar_fluxo(usuario_adm, "G", grafo={"versao": 2, "nos": [], "arestas": []})
