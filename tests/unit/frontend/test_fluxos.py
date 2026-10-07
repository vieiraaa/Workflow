"""Render das telas de fluxos (M2): lista (TEL-04/12) e editor (TEL-05)."""

import json

import pytest
from django.urls import reverse

from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = pytest.mark.modulo("m2")


def nomes(resposta):
    return [t.name for t in resposta.templates]


@pytest.fixture
def fluxo(usuario_coordenador):
    return Fluxo.objects.create(
        nome="Pedidos <b>x</b>", dono=usuario_coordenador, grafo=grafo_inicial()
    )


@pytest.fixture
def fluxo_ativo(usuario_coordenador):
    return Fluxo.objects.create(
        nome="Ativo", dono=usuario_coordenador, grafo=grafo_inicial(), status=Fluxo.ATIVO
    )


def test_lista_vazia_oferece_novo(cliente_coordenador):
    resposta = cliente_coordenador.get(reverse("fluxos:lista"))
    assert "fluxos/lista.html" in nomes(resposta)
    assert b"Nenhum fluxo ainda" in resposta.content
    assert reverse("fluxos:novo").encode() in resposta.content


def test_lista_escapa_nome_e_mostra_acoes(cliente_coordenador, fluxo):
    resposta = cliente_coordenador.get(reverse("fluxos:lista"))
    conteudo = resposta.content.decode()
    assert "<b>x</b>" not in conteudo and "&lt;b&gt;x&lt;/b&gt;" in conteudo
    assert reverse("fluxos:editor", kwargs={"pk": fluxo.pk}) in conteudo
    assert reverse("fluxos:excluir", kwargs={"pk": fluxo.pk}) in conteudo


def test_lista_base_so_executa(cliente_base, fluxo_ativo):
    conteudo = cliente_base.get(reverse("fluxos:lista")).content.decode()
    assert reverse("fluxos:executar", kwargs={"pk": fluxo_ativo.pk}) in conteudo
    assert f'href="{reverse("fluxos:editor", kwargs={"pk": fluxo_ativo.pk})}"' not in conteudo
    assert reverse("fluxos:excluir", kwargs={"pk": fluxo_ativo.pk}) not in conteudo
    assert reverse("fluxos:novo") not in conteudo


def test_lista_busca_sem_resultado(cliente_coordenador, fluxo):
    resposta = cliente_coordenador.get(reverse("fluxos:lista"), {"q": "zzz-nada"})
    assert b"Nenhum fluxo encontrado" in resposta.content


def test_modal_novo_abre_com_erro(cliente_coordenador):
    resposta = cliente_coordenador.post(reverse("fluxos:novo"), {"nome": "", "descricao": ""})
    assert resposta.status_code == 200
    assert "fluxos/lista.html" in nomes(resposta)
    assert b"data-abrir" in resposta.content and b"campo__erro" in resposta.content


def test_editor_usa_template_e_json_script(cliente_coordenador, fluxo):
    resposta = cliente_coordenador.get(reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    assert "fluxos/editor.html" in nomes(resposta)
    assert b'id="grafo-inicial"' in resposta.content
    assert b"data-atualizado-em=" in resposta.content
    assert json.loads(json.dumps(resposta.context["grafo"]))["versao"] == 1


def test_editor_base_recebe_403(cliente_base, fluxo):
    resposta = cliente_base.get(reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    assert resposta.status_code == 403


def test_executar_tem_estado_carregando(cliente_coordenador, fluxo_ativo):
    conteudo = cliente_coordenador.get(reverse("fluxos:lista")).content.decode()
    assert "data-carregando" in conteudo and "Executando…" in conteudo
